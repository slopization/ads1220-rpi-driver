# ads1220-rpi-driver

Raspberry Pi driver for the **TI ADS1220** 24-bit delta-sigma ADC, verified
on a real Raspberry Pi 4B with a **CJMCU-1220** ADS1220 breakout board.

* Full-rate support from **5 SPS (duty-cycle) to 2 kSPS (turbo)** — the
  2 kSPS path was characterised and verified on this hardware (DRDY rate
  ~2.3 kSPS, temperature oracle matching the 20 SPS reference to 0.03 °C).
* Continuous and single-shot modes, all 7 data rates per mode.
* **PGA configuration**: `pga_bypass` (switched-capacitor stage at gain
  1/2/4, forced on for single-ended/monitor muxes) + a deterministic
  `pga_test()` gain-chain verification (MUX 14 zero-differential oracle).
* Differential input (any AIN pair), PGA gain 1–128, internal 2.048 V
  reference, internal temperature sensor.
* Robust high-rate reads and an accurate hardware-timestamped rate meter.
* Gentle lifecycle handling: the ADS1220 is fragile — this driver avoids
  the reset storms that desync the part.

## Wiring

**CJMCU-1220** ADS1220 breakout board (JLCPCB / CJMCU):

| ADS1220 pin | RPi GPIO | SPI role |
|-------------|----------|----------|
| DIN  (CS0)  | GPIO 8   | CE0 (chip select) |
| CLK  (SCLK) | GPIO 11  | SCLK |
| DOUT (MISO) | GPIO 9   | MISO (data out) |
| CS   (MOSI) | GPIO 10  | MOSI (data in)  |
| DRDY      | GPIO 25  | conversion-ready (active LOW) |

> **MOSI/MISO note:** the CJMCU-1220 silkscreen labels the data pins from the
> *device* side, which reads backwards: **CS on the board = MOSI**
> (Pi→ADC data-in) and **DOUT on the board = MISO** (ADC→Pi data-out). Wire by
> electrical role, not by label: `/dev/spidev0.0` MOSI → board CS, MISO ←
> board DOUT. A swapped pair produces exactly the "garbage / 0xFF no data"
> symptom — but before swapping anything, verify wiring with the 20 SPS
> temperature oracle; if it reads a real, stable temperature, the wiring is
> correct and the problem is elsewhere.

## Inputs: mux, single-ended, and monitor muxes

`mux` selects what the ADC measures (REG0 bits 7:4). The driver's `MUXES`
table maps index → (AINP, AINN):

| Mux | AINP | AINN | Meaning |
|-----|------|------|---------|
| 0–7 | AINx | AINy | **Differential** pairs between the four inputs; PGA usable at all gains 1–128 |
| 8–11 | AIN0–3 | AVSS | **Single-ended**: each input vs the board ground (AVSS) |
| 12 | (VREFP−VREFN)/4 | — | **Monitor**: reads the reference voltage (≈ 0.512 V with the 2.048 V internal reference) |
| 13 | (AVDD−AVSS)/4 | — | **Monitor**: reads the analog supply (≈ 0.825 V at 3.3 V AVDD) |
| 14 | (AVDD+AVSS)/2 | shorted | **Monitor/self-test**: AINP and AINN shorted mid-rail → known 0 V differential |

### What a "monitor mux" is

The ADS1220's internal multiplexer has extra switch positions that connect
its **own internal nodes** to the measurement chain instead of the four
external AIN pins:

* **Mux 12** routes `(VREFP − VREFN)/4` — one quarter of the reference
  voltage — to the front end.
* **Mux 13** routes `(AVDD − AVSS)/4` — one quarter of the analog supply —
  to the front end.
* **Mux 14** shorts the measurement inputs to the mid-rail `(AVDD+AVSS)/2`,
  so the differential input is guaranteed 0 V.

They are on-die *diagnostic/health* channels — the same way a µC's ADC often
has a `VDD/3` internal channel. Useful for:

* confirming the ADC + reference + supply are alive with no external wiring,
* building self-calibration points (known voltages you can read at any time),
* `pga_test()` in this driver, which uses **mux 14** as a known-0 V oracle
  to verify the whole gain chain.

Because these internal nodes sit at high common-mode voltages, the datasheet
requires the **PGA to be bypassed** (REG0 bit 0) for muxes 8–13 and limits
them to gains 1/2/4 — the driver enforces both (forces `pga_bypass` on,
rejects the rest with `ConfigError`).

> **CJMCU-1220 note (verified on this board):** the *AIN path* (mux 0–7 and
> the AIN-based mux 14) reads cleanly and was fully verified. The two
> on-chip monitor channels 12/13 behave oddly on this particular board —
> they return a stable but non-intuitive value (e.g. the AVDD/4 channel
> reads ≈ 140 mV and scales oddly with gain) — so treat muxes 12/13 as
> "works, but not the datasheet-expected value" on the CJMCU-1220 and rely
> on the AIN path for real measurements. Mux 14's 0 V differential is
> unaffected by this quirk and is a reliable test oracle.

## Install

```bash
# on the Pi
sudo apt install python3-spidev python3-gpiod
# or via pip
pip install spidev gpiod

# enable SPI (already on by default on Pi OS, but check):
sudo raspi-config   # -> Interface Options -> SPI -> enable
```

Copy this folder somewhere on the Pi (or add it to `PYTHONPATH`), then
`from ads1220 import ADS1220`.

## Quick start

```python
from ads1220 import ADS1220

with ADS1220() as adc:
    adc.reset()                       # once at startup
    adc.set_config(20, "normal", ts=True)   # 20 SPS temperature
    import time; time.sleep(1.0)
    print(f"{adc.read_temp():.2f} C")
```

`ads1220/` is the package, `examples/` has ready-to-run scripts:

```bash
python3 examples/basic_temp.py     # temperature, 20 SPS
python3 examples/ain_input.py      # AIN0-AIN1 differential
python3 examples/turbo_2kps.py     # 2 kSPS (SCLK lowered to 300 kHz)
python3 examples/rate_sweep.py     # verify every rate
python3 examples/pga_test.py       # PGA / gain-chain check (MUX14 0V oracle)
```

## API

### Constructor
```python
ADS1220(bus=0, device=0, drdy_gpio=25, sclk_hz=400_000, settle_s=0.005)
```
* `sclk_hz` — SCLK frequency. **Use ≤ 300 kHz for turbo mode.**

### Configuration
```python
adc.set_config(sps, mode="normal", mux=0, gain=1,
               continuous=True, ts=False, bcs=False)
```
* `sps` — a **nominal SPS value** from the table below (e.g. `20`, `1000`,
  `2000`) **or** the raw DR index `0..6`.
* `mode` — `"normal" | "duty" | "turbo"`.
* `mux` — input pair, index into `MUXES` (0 = AIN0−AIN1). Muxes 8–13
  (single-ended / monitors) only support gain 1/2/4.
* `gain` — one of `GAINS` = 1,2,4,8,16,32,64,128.
* `continuous` — `True` continuous, `False` single-shot.
* `ts` — enable internal temperature sensor.
* Rate changes are preceded by a short reset (gotcha 5) -- the part does not reliably accept consecutive config writes.

Data-rate tables (`DATA_RATES`, datasheet Table 8-12 @ 4.096 MHz clock):

| DR | normal | duty-cycle | turbo |
|----|--------|------------|-------|
| 0  | 20     | 5          | 40    |
| 1  | 45     | 11.25      | 90    |
| 2  | 90     | 22.5       | 180   |
| 3  | 175    | 44         | 350   |
| 4  | 330    | 82.5       | 660   |
| 5  | 600    | 150        | 1200  |
| 6  | 1000   | 250        | **2000** |

### Reading
```python
adc.read_raw()      # -> (b0,b1,b2,b3) raw 4-byte frame
adc.read_code()     # -> signed 24-bit integer
adc.read_voltage(gain, vref=2.048)  # -> volts, V = code*VREF/gain/2^23
adc.read_temp()     # -> degrees C (config with ts=True)

# high-rate safe read:
adc.single_shot()   # START -> DRDY edge -> RDATA; raw frame
adc.read_n(100)     # list of N single-shot frames
adc.stream(50)      # 50 frames in the current (continuous/single) mode
```

### Diagnostics
```python
adc.drdy_rate(3.0)  # measured DRDY Hz (kernel hw timestamps) — robust to 2 kSPS+
adc.nominal_rate()  # nominal SPS of the current config
adc.selftest()      # {'rate_hz':..., 'temp_c':..., 'n_samples':...}
```

## Decoding (reference)

The 4 RDATA bytes combine into a signed 24-bit word with this verified
framing (the ADS1220 shifts DOUT out one bit early on the first CS pulse):

```
W = (b0 & 0x7F) << 17 | b1 << 9 | b2 << 1 | (b3 >> 7)     # 24-bit 2's-complement
```
* **Voltage:** `V = W * VREF / gain / 2^23` (internal `VREF = 2.048 V`).
* **Temperature:** the 14-bit code is the top 14 bits of `W`, two's
  complement, LSB `0.03125 °C`:
  `t14 = (W >> 10) & 0x3FFF; t14 -= 0x4000 if t14 >= 0x2000; T = t14*0.03125`.

## Verified behaviour / gotchas

These were established on the real part — keep them:

1. **SPI mode 1 only** (CPOL=0, CPHA=1). Other modes desync the part.
2. **SCLK ≤ 300 kHz in turbo mode.** At 500 kHz the internal oscillator
   isn't fully powered at START and single-shot results come back corrupt/low.
3. **Measure rate with DRDY hardware edge timestamps**, not by counting
   fresh DOUT frames (the DOUT pattern changes on every RDATA poll, so
   dedup-based counting saturates at loop speed) and not by value-polling
   (aliasing at 2 kSPS).
4. **Read with the single-shot sequence at high rate** (START → wait DRDY
   falling edge → RDATA). Blind RDATA polling at ~2 kSPS lands at random
   phases of the 0.5 ms conversion cycle and returns mid-frame garbage.
   The fixed per-cycle transaction keeps a constant SCLK phase so framing
   stays stable.
5. **The part is fragile.** Avoid back-to-back POWERDOWN+RESET cycles
   (they can desync even a freshly powered part). A desynced part shows
   DRDY stuck low and `RDATA = 0xFF FF FF FF`; **only a full power cycle
   recovers it.** This driver resets once at startup and again before
   every rate/mode change: consecutive config writes are not reliably
   accepted by the part (a dropped WREG leaves the ADC stuck at the
   previous rate). One RESET per change is safe; only repeated
   POWERDOWN+RESET storms desync it.
6. **Rate is nominal ± clock.** With the internal oscillator (no external
   4.096 MHz clock) rates run slightly fast — 2 kSPS measures ~2.3 kSPS.

## Troubleshooting

| Symptom | Likely cause / fix |
|---------|--------------------|
| `RDATA = 0xFF FF FF FF` | Conversion not ready, or part desynced. Check rate vs conversion time; if DRDY is stuck low, **power-cycle the board**. |
| `too few DRDY edges captured` | Device not converting (wrong mode/DR, or desynced). Power-cycle. |
| Rate much lower than set | Value-poll aliasing or ring overflow. Use `drdy_rate()` (edge timestamps). |
| Rate stuck at the previous setting after a change | Consecutive config writes dropped by the part. `set_config()` already resets first; if issuing raw WREGs, reset between rates. |
| Garbage data at 2 kSPS | SCLK too high, or blind-poll aliasing. Lower SCLK to ≤300 kHz; use `single_shot()`. |
| Temperature far from expected at turbo | SCLK > 300 kHz corrupting single-shot. Lower SCLK. |
| `RDATA` works but voltage is off | Wrong gain, or single-ended mux needs gain 1/2/4. |

## Documentation

Full docs live in [`docs/`](docs/README.md):

| Doc | Topic |
|-----|-------|
| [docs/01-wiring](docs/01-wiring.md) | pinout, MOSI/MISO naming trap, SPI setup |
| [docs/02-installation](docs/02-installation.md) | dependencies, install, first check |
| [docs/03-quickstart](docs/03-quickstart.md) | 5-minute examples |
| [docs/04-api-reference](docs/04-api-reference.md) | complete API reference |
| [docs/05-protocol-and-registers](docs/05-protocol-and-registers.md) | SPI commands, register map, timing |
| [docs/06-decoding](docs/06-decoding.md) | 24-bit framing, voltage & temperature math |
| [docs/07-data-rates](docs/07-data-rates.md) | all 14 rates, mode change, rate measurement |
| [docs/08-troubleshooting](docs/08-troubleshooting.md) | symptom → fix, the desync state |

## Files

```
ads1220-rpi-driver/
├── README.md
├── requirements.txt
├── ads1220/
│   ├── __init__.py        # package exports
│   ├── _driver.py         # ADS1220 class
│   └── __main__.py        # CLI: python -m ads1220 ...
├── docs/
│   ├── README.md          # doc index
│   └── 01…08-*.md         # wiring → troubleshooting
└── examples/
    ├── basic_temp.py
    ├── ain_input.py
    ├── turbo_2kps.py
    ├── rate_sweep.py
    └── pga_test.py        # PGA / gain-chain verification
```

## Disclaimer

Verified against one CJMCU-1220 ADS1220 breakout on a Raspberry Pi 4B. The ADS1220 is
sensitive to SPI timing and reset patterns; if you see unexpected behaviour,
consult the TI datasheet (SBAS501) and start with the 20 SPS temperature
oracle to confirm wiring and decoding before moving to high rates.
