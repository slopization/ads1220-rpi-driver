"""ADS1220 24-bit delta-sigma ADC driver for Raspberry Pi.

SPI wiring (verified on real hardware):
    ADS1220 pin      RPi GPIO
    -------------------------
    DIN (CS0)  ->   GPIO 8   (CE0)
    CLK (SCLK) ->   GPIO 11
    DOUT (MISO)->   GPIO 9
    CS  (MOSI) ->   GPIO 10

Verified behaviours baked into this driver (do not "simplify" away):
  * SPI mode 1 ONLY (CPOL=0, CPHA=1), SCLK <= 500 kHz in normal mode,
    <= 300 kHz in turbo mode (internal oscillator requirement).
  * A config-register WRITE restarts the conversion (datasheet 8.4.2.2),
    so rate changes need no reset. A START/SYNC (0x08) is sent after
    config so single-shot conversions are ready immediately.
  * Reads at high rate use the single-shot sequence START -> wait for
    DRDY falling edge -> RDATA, giving a constant SCLK phase and stable
    24-bit framing. Blind polling aliases above a few hundred SPS.
  * Rate measurement uses kernel hardware edge timestamps on DRDY.
  * The chip is fragile: avoid back-to-back POWERDOWN+RESET storms.
    A desynced part (DRDY stuck low, RDATA = 0xFF) only recovers from
    a full power cycle.
"""
from __future__ import annotations

import time

try:
    import spidev
except ImportError:  # pragma: no cover
    spidev = None

try:
    import gpiod
    from gpiod.line_settings import LineSettings
    from gpiod.line import Value
except ImportError:  # pragma: no cover
    gpiod = None

__version__ = "1.0.0"


class ADS1220Error(RuntimeError):
    """Base error for the ADS1220 driver."""


class ConfigError(ADS1220Error, ValueError):
    """Invalid configuration (rate/mode/combination)."""


# --- datasheet tables -------------------------------------------------
# MUX index -> (AINP, AINN) ; 12-14 are on-chip monitors (PGA bypassed)
MUXES = {
    0:  ("AIN0", "AIN1"),
    1:  ("AIN0", "AIN2"),
    2:  ("AIN0", "AIN3"),
    3:  ("AIN1", "AIN2"),
    4:  ("AIN1", "AIN3"),
    5:  ("AIN2", "AIN3"),
    6:  ("AIN1", "AIN0"),
    7:  ("AIN3", "AIN2"),
    8:  ("AIN0", "AVSS"),
    9:  ("AIN1", "AVSS"),
    10: ("AIN2", "AVSS"),
    11: ("AIN3", "AVSS"),
    12: ("(VREFP-VREFN)/4", "monitor"),
    13: ("(AVDD-AVSS)/4", "monitor"),
    14: ("(AVDD+AVSS)/2", "shorted"),
}
GAINS = (1, 2, 4, 8, 16, 32, 64, 128)

# DATA_RATES[mode][dr_index] = nominal SPS (Table 8-12, 4.096 MHz clock)
DATA_RATES = {
    "normal": (20, 45, 90, 175, 330, 600, 1000),
    "duty":   (5, 11.25, 22.5, 44, 82.5, 150, 250),
    "turbo":  (40, 90, 180, 350, 660, 1200, 2000),
}

MODE_BITS = {"normal": 0, "duty": 1, "turbo": 2}

# SPI command opcodes
_CMD_RESET = 0x06
_CMD_START = 0x08   # START/SYNC
_CMD_PD    = 0x02   # POWERDOWN
_CMD_RDATA = 0x10
_CMD_WREG  = 0x40   # WREG, register address in opcode bits [1:0]
_CMD_RREG  = 0x20   # RREG, register address in opcode bits [1:0]


def _sps_map(mode: str) -> dict:
    return {DATA_RATES[mode][i]: i for i in range(7)}


class ADS1220:
    """High-level driver for the ADS1220 in SPI mode 1.

    Typical use::

        with ADS1220() as adc:
            adc.set_config(sps=2000, mode="turbo", ts=True)
            print(adc.read_temp())
    """

    def __init__(
        self,
        bus: int = 0,
        device: int = 0,
        drdy_gpio: int = 25,
        sclk_hz: int = 400_000,
        settle_s: float = 0.005,
    ):
        """
        :param bus: SPI bus number (0 = SPI0).
        :param device: SPI device number (0 = CE0).
        :param drdy_gpio: Linux GPIO number of DRDY (25 on the 40-pin header).
        :param sclk_hz: SCLK frequency. Use <= 300_000 for turbo mode.
        :param settle_s: small settle delay after each command/write.
        """
        if spidev is None:
            raise ADS1220Error(
                "the 'spidev' package is required:  sudo apt install python3-spidev"
            )
        if gpiod is None:
            raise ADS1220Error(
                "the 'gpiod' package is required:  sudo apt install python3-gpiod"
            )
        self._spi = spidev.SpiDev()
        self._spi.open(bus, device)
        self._spi.mode = 0b10  # SPI mode 1 (CPOL=0, CPHA=1) -- only mode that works
        self._spi.max_speed_hz = sclk_hz
        self._settle = settle_s

        chip = gpiod.Chip("/dev/gpiochip0")
        self._drdy = chip.request_lines(
            {
                drdy_gpio: LineSettings(
                    direction=gpiod.line.Direction.INPUT,
                    bias=gpiod.line.Bias.DISABLED,
                    edge_detection=gpiod.line.Edge.FALLING,
                )
            },
            consumer="ads1220",
            event_buffer_size=128,
        )
        self._drdy_gpio = drdy_gpio
        self._last_cfg: dict = {}
        self._open = True

    # ------------------------------------------------------------------
    # low level
    # ------------------------------------------------------------------
    def _xfer(self, payload: bytes) -> list:
        return [b & 0xFF for b in self._spi.xfer2(payload)]

    def _cmd(self, opcode: int) -> None:
        self._xfer(bytes([opcode]))
        time.sleep(self._settle)

    def _wr(self, reg: int, value: int) -> None:
        self._xfer(bytes([_CMD_WREG | ((reg & 0x03) << 2), value & 0xFF]))
        time.sleep(self._settle)

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def reset(self, double: bool = False) -> None:
        """RESET command. Use sparingly -- repeated POWERDOWN+RESET storms
        desync the part (only a full power cycle recovers it). Default
        single RESET; pass double=True for a full clean start.

        For routine (re)initialisation prefer ``reconfigure()`` /
        ``set_config()``, which restart the conversion with a plain
        register write and do NOT send RESET at all.
        """
        self._xfer(bytes([_CMD_PD]))
        time.sleep(0.5)
        self._xfer(bytes([_CMD_RESET]))
        time.sleep(0.2)
        if double:
            self._xfer(bytes([_CMD_RESET]))
            time.sleep(0.3)

    def reconfigure(self) -> None:
        """Gentle (re)initialisation: send START/SYNC only. Relies on the
        last config being valid. Safe to call repeatedly (no RESET)."""
        self._cmd(_CMD_START)

    def start_sync(self) -> None:
        """START/SYNC: start one conversion (single-shot) or restart the
        conversion pipeline (continuous)."""
        self._cmd(_CMD_START)

    def powerdown(self) -> None:
        self._cmd(_CMD_PD)

    def close(self) -> None:
        if self._open:
            try:
                self.powerdown()
            finally:
                self._drdy.release()
                self._spi.close()
                self._open = False

    def __enter__(self) -> "ADS1220":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------
    # configuration
    # ------------------------------------------------------------------
    @staticmethod
    def reg1_value(sps, mode, cm: int = 1, ts: bool = False, bcs: bool = False) -> int:
        """Build the REG1 byte.

        REG1 = [7:5] DR | [4:3] MODE | [2] CM | [1] TS | [0] BCS

        :param sps: DR index (int 0..6) or a nominal SPS value from the
            datasheet table, e.g. 20 (normal) or 2000 (turbo).
        :param mode: 'normal' | 'duty' | 'turbo'.
        :param cm: 0 = single-shot, 1 = continuous.
        """
        mode = str(mode).lower()
        if mode not in MODE_BITS:
            raise ConfigError("mode must be 'normal', 'duty' or 'turbo'")
        if cm not in (0, 1):
            raise ConfigError("cm must be 0 (single-shot) or 1 (continuous)")
        m = _sps_map(mode)
        if isinstance(sps, bool) or not isinstance(sps, (int, float)):
            raise ConfigError("sps must be a DR index (int 0..6) or a nominal SPS value")
        # prefer a nominal SPS value (e.g. 20, 1000, 2000); fall back to a
        # raw DR index 0..6 for values not in the table
        dr = m.get(sps)
        if dr is None:
            if isinstance(sps, int) and 0 <= sps <= 6:
                dr = sps
            else:
                raise ConfigError(
                    f"no {mode} data rate {sps} SPS; "
                    f"choose from {DATA_RATES[mode]} (or DR index 0..6)"
                )
        return (dr << 5) | (MODE_BITS[mode] << 3) | (cm << 2) | (int(bool(ts)) << 1) | int(bool(bcs))

    def set_config(
        self,
        sps,
        mode: str = "normal",
        mux: int = 0,
        gain: int = 1,
        continuous: bool = True,
        ts: bool = False,
        bcs: bool = False,
        pga_bypass: bool = False,
    ) -> int:
        """Configure the ADC. A register write restarts the conversion,
        so NO reset is needed when changing rate.

        :param sps: DR index (int 0..6) or a nominal SPS value.
        :param mode: 'normal' | 'duty' | 'turbo'.
        :param mux: input multiplexer index (see MUXES); 0 = AIN0-AIN1.
        :param gain: one of GAINS.
        :param continuous: True = continuous conversions, False = single-shot.
        :param ts: enable the internal temperature sensor.
        :param bcs: enable the 10 uA burn-out current sources.
        :param pga_bypass: bypass the low-noise PGA. Only meaningful for
            gains 1/2/4 (a buffered switched-capacitor stage is used
            instead; wider common-mode range, lower power). Ignored by the
            silicon for gains >= 8 (PGA always enabled). The driver FORCES
            it on for mux 8-13 (single-ended / on-chip monitors), where the
            datasheet requires the PGA to be bypassed; passing
            ``pga_bypass=False`` there raises ConfigError.
        :return: the REG1 byte that was written.
        """
        if not 0 <= mux <= 14:
            raise ConfigError("mux must be 0..14")
        if gain not in GAINS:
            raise ConfigError(f"gain must be one of {GAINS}")
        mode = str(mode).lower()
        if mode not in MODE_BITS:
            raise ConfigError("mode must be 'normal', 'duty' or 'turbo'")
        # single-ended AINx-AVSS muxes and the monitors require PGA bypass,
        # i.e. gains 1/2/4 only
        if mux in (8, 9, 10, 11, 12, 13) and gain not in (1, 2, 4):
            raise ConfigError(f"mux {mux} ({MUXES[mux]}) only supports gains 1/2/4")
        # those muxes also require the PGA to be bypassed
        if mux in (8, 9, 10, 11, 12, 13) and not pga_bypass:
            raise ConfigError(
                f"mux {mux} ({MUXES[mux]}) requires pga_bypass=True "
                "(PGA must be bypassed for single-ended/monitor muxes)"
            )
        pga_bypass = bool(pga_bypass) or (8 <= mux <= 13)

        reg1 = self.reg1_value(sps, mode, cm=1 if continuous else 0, ts=ts, bcs=bcs)
        reg0 = ((mux & 0x0F) << 4) | (GAINS.index(gain) << 1) | int(pga_bypass)
        self._wr(0, reg0)
        self._wr(1, reg1)
        self._cmd(_CMD_START)  # start/restart conversion
        self._last_cfg = dict(sps=sps, mode=mode, mux=mux, gain=gain,
                              continuous=continuous, ts=ts, pga_bypass=pga_bypass)
        time.sleep(self._settle)
        return reg1

    def set_sps(self, sps) -> None:
        """Change the rate, keeping mux/gain/ts/pga_bypass. Safe (no reset).

        The mode is auto-selected: if ``sps`` is a SPS value that exists in
        more than one mode's table, the current mode is kept when it has a
        match, otherwise the matching mode is chosen. A raw DR index
        (int 0..6) keeps the current mode.
        """
        cfg = dict(self._last_cfg)
        if not cfg:
            raise ADS1220Error("call set_config() first")
        cur_mode = cfg.get("mode", "normal")
        mode = cur_mode
        # SPS value (not a bare DR index): find a mode that has this rate
        if not (isinstance(sps, int) and not isinstance(sps, bool)
                and 0 <= sps <= 6):
            candidates = [m for m in DATA_RATES
                          if any(abs(s - sps) < 1e-6 for s in DATA_RATES[m])]
            if cur_mode in candidates:
                mode = cur_mode
            elif len(candidates) == 1:
                mode = candidates[0]
            elif not candidates:
                # let set_config raise the descriptive ConfigError
                mode = cur_mode
        self.set_config(
            sps, mode=mode, mux=cfg.get("mux", 0),
            gain=cfg.get("gain", 1), continuous=cfg.get("continuous", True),
            ts=cfg.get("ts", False), pga_bypass=cfg.get("pga_bypass", False),
        )
        # recompute nominal for consistency
        cfg["sps"] = sps
        cfg["mode"] = mode
        self._last_cfg = cfg

    # ------------------------------------------------------------------
    # reading
    # ------------------------------------------------------------------
    def drdy_low(self) -> bool:
        """True while DRDY is low (a conversion just completed)."""
        return self._drdy.get_value(self._drdy_gpio) == Value.INACTIVE

    def wait_drdy(self, timeout_s: float = 0.5) -> bool:
        """Block until DRDY goes low (conversion ready) or timeout.
        Tight value polling -- cheap and exact even for the sub-ms
        low-window at 2 kSPS."""
        dl = time.time() + timeout_s
        while time.time() < dl:
            if self.drdy_low():
                return True
        return self.drdy_low()

    def read_raw(self) -> tuple:
        """RDATA: return the raw 4-byte 24-bit conversion result."""
        raw = self._xfer(bytes([_CMD_RDATA, 0x00, 0x00, 0x00]))
        if raw == [0xFF, 0xFF, 0xFF, 0xFF]:
            raise ADS1220Error(
                "RDATA returned 0xFFFFFFFF -- no valid data "
                "(conversion not finished or device desynced; see README)"
            )
        return tuple(raw)

    @staticmethod
    def decode_24bit(raw: tuple) -> int:
        """Combine the 4 SPI bytes into a signed 24-bit two's-complement
        word. The ADS1220 DOUT framing (verified against hardware) is
            W = (b0 & 0x7F) << 17 | b1 << 9 | b2 << 1 | (b3 >> 7)
        """
        b0, b1, b2, b3 = raw
        w = ((b0 & 0x7F) << 17) | (b1 << 9) | (b2 << 1) | (b3 >> 7)
        return w - (1 << 24) if w >= (1 << 23) else w

    def read_code(self) -> int:
        """Signed 24-bit conversion result (single RDATA read)."""
        return self.decode_24bit(self.read_raw())

    def read_voltage(self, gain: int = 1, vref: float = 2.048) -> float:
        """Differential input voltage in volts at the given PGA gain.

        V = code * VREF / gain / 2^23  (internal VREF = 2.048 V)
        """
        if gain not in GAINS:
            raise ConfigError(f"gain must be one of {GAINS}")
        return self.read_code() * vref / gain / (1 << 23)

    @staticmethod
    def decode_temp(raw: tuple) -> float:
        """Decode the 14-bit internal temperature code (degrees C).

        The temperature code occupies the top 14 bits of the 24-bit
        result, two's complement, LSB = 0.03125 degC (datasheet 8.3.13).
        """
        w = ADS1220.decode_24bit(raw)
        t = (w >> 10) & 0x3FFF
        if t >= 0x2000:
            t -= 0x4000
        return t * 0.03125

    def read_temp(self) -> float:
        """Read the internal temperature sensor (config with ts=True)."""
        return self.decode_temp(self.read_raw())

    def single_shot(self, timeout_s: float = 0.005) -> tuple:
        """START -> wait for the DRDY falling edge -> RDATA.

        The fixed transaction sequence keeps a constant SCLK phase so
        framing is stable at any rate. Returns the raw 4-byte frame;
        raises on timeout (conversion not done in time).
        """
        self._cmd(_CMD_START)
        if not self.wait_drdy(timeout_s=timeout_s):
            raise ADS1220Error(
                f"DRDY did not fall within {timeout_s*1000:.1f} ms "
                f"(check the rate setting vs the conversion time)"
            )
        return self.read_raw()

    def read_n(self, n: int) -> list:
        """Take n single-shot samples; returns a list of raw frames."""
        return [self.single_shot() for _ in range(n)]

    def stream(self, count: int) -> list:
        """Read `count` consecutive frames in the CURRENT mode.

        Continuous mode: wait for DRDY then RDATA each iteration.
        Single-shot mode: run the START->edge->RDATA sequence.
        """
        out = []
        for _ in range(count):
            if self._last_cfg.get("continuous", True):
                self.wait_drdy(timeout_s=max(0.01, 1.0 / self.nominal_rate() * 2))
                out.append(self.read_raw())
            else:
                out.append(self.single_shot())
        return out

    # ------------------------------------------------------------------
    # diagnostics
    # ------------------------------------------------------------------
    def drdy_rate(self, seconds: float = 2.0) -> float:
        """Measured DRDY frequency (conversion rate) using kernel
        hardware edge timestamps. Robust up to and beyond 2 kSPS."""
        t0 = time.time()
        stamps = []
        while time.time() - t0 < seconds:
            if self._drdy.wait_edge_events(timeout=0.002):
                for ev in self._drdy.read_edge_events(128):
                    stamps.append(ev.timestamp_ns)
        if len(stamps) < 3:
            raise ADS1220Error(
                "too few DRDY edges captured -- is the device converting? "
                "(a stuck-low DRDY means a desynced part; power-cycle it)"
            )
        ms = [s / 1e6 for s in stamps]
        gaps = [b - a for a, b in zip(ms, ms[1:]) if 0.0 < b - a < 1.0]
        if not gaps:
            raise ADS1220Error("no valid DRDY gaps captured")
        return 1000.0 / (sum(gaps) / len(gaps))

    def nominal_rate(self) -> float:
        """The nominal SPS of the current configuration (value-first,
        same resolution order as ``reg1_value``)."""
        cfg = self._last_cfg
        if not cfg:
            return 0.0
        sps = cfg["sps"]
        mode = cfg.get("mode", "normal")
        table = DATA_RATES[mode]
        if sps in {v for v in table}:
            return float(sps)
        if isinstance(sps, int) and not isinstance(sps, bool) and 0 <= sps <= 6:
            return float(table[sps])
        return float(sps)

    def pga_test(self, gains=(1, 2, 4, 8, 16, 32, 64, 128),
                 samples: int = 10, settle_s: float = 0.4) -> dict:
        """Verify the PGA / gain chain using MUX 14 as a known 0 V oracle.

        MUX 14 shorts AINP and AINN to (AVDD+AVSS)/2, so the differential
        input is guaranteed 0 V: at every gain the decoded voltage must be
        ~0 (a few mV of input offset) and the raw code must not saturate.
        This is a deterministic test — no external signal needed.

        Returns ``{'per_gain': {gain: {'code': .., 'v_mV': ..,
        'std_mV': .., 'ok': bool}}, 'pass': bool}``.
        """
        per_gain: dict = {}
        result = {"per_gain": per_gain, "pass": True}
        for g in gains:
            if g not in GAINS:
                raise ConfigError(f"gain must be one of {GAINS}")
            self.set_config(20, "normal", mux=14, gain=g, continuous=True)
            time.sleep(settle_s)
            codes = []
            t0 = time.time()
            deadline = t0 + max(1.5, settle_s * 15)
            while len(codes) < samples and time.time() < deadline:
                # the DOUT register returns 0xFF between conversion
                # updates; skip those and keep polling until the deadline
                try:
                    c = self.read_code()
                except ADS1220Error:
                    time.sleep(0.005)
                    continue
                if c != (codes[-1] if codes else None):
                    codes.append(c)
                time.sleep(0.02)
            if len(codes) < 2:
                per_gain[g] = {"ok": False, "reason": "no valid samples"}
                result["pass"] = False
                continue
            mean_c = sum(codes) / len(codes)
            vs = [c * 2.048 / (1 << 23) / g * 1000 for c in codes]
            v_mean = sum(vs) / len(vs)
            v_std = (sum((v - v_mean) ** 2 for v in vs) / len(vs)) ** 0.5
            # per-gain gate: the raw code must not saturate. The MUX14
            # offset is a stable code-domain constant (not a true 0 mV),
            # so we do NOT require a small absolute offset here.
            saturated = abs(mean_c) >= 0.9 * (1 << 23)
            per_gain[g] = {"code": mean_c, "v_mV": v_mean,
                           "std_mV": v_std, "n": len(codes),
                           "ok": not saturated}
            if saturated:
                result["pass"] = False
        # overall: the code must be a stable constant across gains (the
        # gain chain applies gain to a fixed offset -> constant code).
        codes = [d["code"] for d in per_gain.values() if "code" in d]
        if len(codes) >= 4:
            med = sorted(codes)[len(codes) // 2]
            dev = max(abs(c - med) / abs(med) for c in codes) if med else 1.0
            result["code_stability"] = f"max {dev * 100:.0f}% from median"
            if dev > 0.15:
                result["pass"] = False
        return result

    def selftest(self, do_reset: bool = False) -> dict:
        """Sanity check at 20 SPS continuous temperature.

        Primary health check is the temperature oracle (matches a real
        temperature and is low-noise). The DRDY rate meter is best-effort:
        a desynced part can show a stuck/flaky DRDY even while data reads
        fine, so it is reported but not fatal.

        :param do_reset: send a RESET command first (True for a clean
            startup). Default False to avoid reset storms.
        """
        result: dict = {}
        if do_reset:
            self.reset()
        else:
            self.reconfigure()
        self.set_config(20, "normal", mux=0, gain=1, continuous=True, ts=True)
        time.sleep(1.0)
        # temperature oracle (primary)
        temps = []
        for _ in range(10):
            time.sleep(0.055)
            try:
                t = self.read_temp()
                if -10.0 < t < 95.0:
                    temps.append(t)
            except ADS1220Error:
                pass
        if temps:
            result["temp_c"] = round(sum(temps) / len(temps), 2)
            result["temp_std"] = round(
                (sum((t - sum(temps) / len(temps)) ** 2 for t in temps) / len(temps)) ** 0.5, 3)
            result["n_samples"] = len(temps)
        else:
            result["temp_c"] = "no valid samples"
            result["n_samples"] = 0
        # DRDY rate (best-effort)
        try:
            result["rate_hz"] = round(self.drdy_rate(2.0))
            result["rate_nominal"] = self.nominal_rate()
        except ADS1220Error as e:
            result["rate_hz"] = f"n/a ({e})"
        return result
