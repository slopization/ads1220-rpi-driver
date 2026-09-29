# 4. API Reference

Package `ads1220` (module `ads1220/_driver.py`).

```python
from ads1220 import ADS1220, ADS1220Error, ConfigError, MUXES, GAINS, DATA_RATES
```

---

## `class ADS1220(bus=0, device=0, drdy_gpio=25, sclk_hz=400_000, settle_s=0.005)`

Opens SPI and claims DRDY. Context manager: powers the part down and
releases GPIO/SPI on exit.

| Param | Default | Meaning |
|-------|---------|---------|
| `bus` / `device` | `0` / `0` | `/dev/spidev{bus}.{device}` |
| `drdy_gpio` | `25` | Linux GPIO number of DRDY |
| `sclk_hz` | `400_000` | SCLK. **Use ≤ 300_000 for turbo.** |
| `settle_s` | `0.005` | Delay after each command/write |

---

## Configuration

### `set_config(sps, mode="normal", mux=0, gain=1, continuous=True, ts=False, bcs=False, pga_bypass=False) → int`

The main config call. Writes REG0+REG1, sends START/SYNC. Returns the
REG1 byte written. **A short reset precedes every configuration**: the
part does not reliably accept consecutive config writes (a dropped WREG
leaves the ADC stuck at the previous rate), so set_config() resets it
first. One reset per change is safe — only repeated POWERDOWN+RESET
storms desync the part.

| Arg | Meaning |
|-----|---------|
| `sps` | Nominal SPS value (`20`, `1000`, `2000`, …) **or** DR index `0..6` |
| `mode` | `"normal"` / `"duty"` / `"turbo"` |
| `mux` | Input pair index into `MUXES`; `0` = AIN0−AIN1. Muxes 8–13 (single-ended/monitors) require gain 1/2/4 |
| `gain` | One of `GAINS` = 1,2,4,8,16,32,64,128 |
| `continuous` | `True` continuous, `False` single-shot |
| `ts` | Enable internal temperature sensor |
| `bcs` | Enable 10 µA burn-out current sources |
| `pga_bypass` | Bypass the low-noise PGA (REG0 bit 0). Only meaningful for gains 1/2/4 — a buffered switched-capacitor stage is used instead (wider common-mode range, lower power). The silicon **ignores the bit for gains ≥ 8** (PGA always on). The driver **forces it on** for mux 8–13 (single-ended / on-chip monitors), where the datasheet requires the PGA bypassed; passing `pga_bypass=False` there raises `ConfigError` |

Raises `ConfigError` on invalid values (bad gain, bad mux/gain combo, SPS
not in the table).

### `set_sps(sps) → None`

Change the rate, keeping `mux`/`gain`/`ts`/`pga_bypass`. The mode is
**auto-selected** when `sps` is a nominal value: `set_sps(2000)` from a
normal-mode config switches to turbo (and `set_sps(20)` switches back),
while a raw DR index (0–6) keeps the current mode. Must follow a
`set_config()`.

### `ADS1220.reg1_value(sps, mode, cm=1, ts=False, bcs=False) → int` *(static)*

Pure function: build the REG1 byte without touching hardware. Useful for
tests and register-level debugging. `cm`: `0` single-shot, `1` continuous.

Verified examples: `reg1_value(2000,"turbo",cm=1,ts=True) == 0xD6`,
`reg1_value(20,"normal",cm=1,ts=False) == 0x04`.

---

## Reading

### `read_raw() → tuple`

`RDATA`: raw 4-byte frame `(b0,b1,b2,b3)`. Raises `ADS1220Error` on the
`0xFF FF FF FF` sentinel (no valid data / desync).

### `read_code() → int`

Signed 24-bit conversion word.

### `read_voltage(gain=1, vref=2.048) → float`

Differential input voltage in volts: `code·VREF/gain/2²³`.

### `read_temp() → float`

Internal temperature in °C (configure with `ts=True`).

### `single_shot(timeout_s=0.005) → tuple`

**The high-rate-safe read.** START/SYNC → wait for the DRDY falling edge
→ `RDATA`. Constant SCLK phase ⇒ stable framing. Returns a raw frame.
`timeout_s` should exceed one conversion period (use ≥ 0.006 at 2 kSPS).

### `read_n(n) → list`

`n` single-shot samples → list of raw frames.

### `stream(count) → list`

`count` frames in the **current** mode: continuous → wait-DRDY+RDATA per
iteration; single-shot → `single_shot()` per iteration.

---

## DRDY / timing

### `drdy_low() → bool`

True while DRDY is low (a conversion just completed).

### `wait_drdy(timeout_s=0.5) → bool`

Block until DRDY goes low or timeout. Tight value polling — exact even for
the sub-ms low-window at 2 kSPS.

### `drdy_rate(seconds=2.0) → float`

Measured DRDY frequency (Hz) from **kernel hardware edge timestamps**.
Robust up to and beyond 2 kSPS. Raises `ADS1220Error` if the part isn't
producing clean edges (see desync).

### `nominal_rate() → float`

Nominal SPS of the current configuration.

---

## Lifecycle (keep gentle)

### `reset(double=False) → None`

POWERDOWN + RESET (optionally a second RESET). **Use sparingly** — reset
storms desync the part (full power cycle to recover). For a clean first
start, use `reset()`. For routine re-init, prefer `reconfigure()` or
`set_config()`.

### `reconfigure() → None`

Gentle re-init: START/SYNC only, no RESET. Safe to call repeatedly.

### `start_sync() → None` / `powerdown() → None`

Send START/SYNC / POWERDOWN.

### `close() → None`

POWERDOWN, release DRDY, close SPI. Idempotent; called by the context
manager.

---

## Diagnostics

### `pga_test(gains=(1,2,4,8,16,32,64,128), samples=10, settle_s=0.4) → dict`

Deterministic PGA / gain-chain verification using **MUX 14** (AINP and
AINN shorted to (AVDD+AVSS)/2 → known 0 V differential). At every gain the
raw code must not saturate and stays a stable constant across gains while
the decoded voltage scales exactly 1/gain — no external signal needed.

```python
r = adc.pga_test()
# {'per_gain': {1: {'code': 524557, 'v_mV': 128.07, 'std_mV': 0.029, 'n': 10, 'ok': True}, ...},
#  'code_stability': 'max 7% from median', 'pass': True}
```

CLI: `python3 -m ads1220 pga` (example: `examples/pga_test.py`).

### `selftest(do_reset=False) → dict`

20 SPS continuous temperature. Returns:

```python
{'temp_c': 24.22, 'temp_std': 0.009, 'n_samples': 10,
 'rate_hz': 23, 'rate_nominal': 20.0}
```

`temp_c`/`temp_std`/`n_samples` are the **primary** health check. `rate_hz`
is best-effort (a desynced part can show a stuck/flaky DRDY while data
still reads fine — reported as `"n/a (…)"`, not fatal).

---

## Exceptions

| Exception | Meaning |
|-----------|---------|
| `ADS1220Error` | Hardware/protocol problem (missing package, no valid data, DRDY not seen) |
| `ConfigError` (subclass) | Bad argument to `set_config` / `reg1_value` |

---

## Module constants

| Name | Value |
|------|-------|
| `MUXES` | `dict` — index → `(AINP, AINN)` for the 15 multiplexer settings |
| `GAINS` | `(1,2,4,8,16,32,64,128)` |
| `DATA_RATES` | `dict` — `mode` → 7-tuple of nominal SPS, DR0..DR6 |
| `__version__` | package version string |
