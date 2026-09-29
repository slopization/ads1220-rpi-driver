# 8. Troubleshooting

The ADS1220 fails in a small number of very specific ways. This page maps
symptoms to causes, and documents the **desync** state and how to recover.

## Symptom → cause → fix

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `RDATA` = `FF FF FF FF` always | Conversion not ready **or** part desynced | Check rate vs. conversion time; if DRDY is stuck LOW → power-cycle (below) |
| `selftest` temp = "no valid samples" | Wiring, desync, or SPI mode error | Verify wiring (MOSI/MISO roles); confirm SPI mode 1; power-cycle |
| `ADS1220Error: no valid DRDY gaps` | DRDY not toggling cleanly (desync or DRDY line miswired) | Check GPIO 25 wiring; power-cycle the board. If rates were changed without resets, the part may be stuck at the previous rate -- reconfigure through `set_config()` (it resets first) |
| Temperature far from room temp (e.g. −240 °C, +113 °C) | Wrong framing offset (0- or 2-bit) | Use the driver's `decode_24bit` (1-bit offset, verified); do not re-derive |
| Temperature ~12–24 °C low at 2 kSPS single-shot, correct at 20 SPS | **SCLK > 300 kHz in turbo** (internal oscillator not fully powered at START) | `ADS1220(sclk_hz=300_000)` for any turbo use |
| Garbage / wildly varying AIN at 2 kSPS | Blind RDATA polling aliasing (random phase of 0.5 ms cycle) | Use `single_shot()` |
| Measured rate ≈ 200 Hz at 2 kSPS setting | DRDY value-poll aliasing (catches 30–50 % of edges) | Use `drdy_rate()` (kernel edge timestamps) |
| Measured rate ≈ 1450 Hz regardless of setting | DOUT frame-count saturation | Same fix — frame counting is invalid, use `drdy_rate()` |
| Same period for several different rate settings | Device half-dead, or rate write not landed | Confirm REG1 write (readback); power-cycle; verify with a fresh write |
| Gain scaling off | Mismatch between `set_config(gain=…)` and `read_voltage(gain=…)` | Keep both the same; single-ended muxes (8–13) only support gain 1/2/4 |
| `ConfigError: no <mode> data rate …` | SPS value not in the table (e.g. 100) | Use a table value (20/45/90/… or 2000) or a DR index 0–6 |
| `ModuleNotFoundError: spidev/gpiod` | Missing package | `sudo apt install python3-spidev python3-gpiod` |
| `/dev/spidev0.0` missing | SPI disabled | `sudo raspi-config` → SPI enable → reboot |

## The desync state (most important)

**Signature:** DRDY stuck LOW (or missing edges), `RDATA` returns
`FF FF FF FF`, config writes seem ignored — **but occasionally a valid
temperature frame still slips through** (half-desynced).

**What causes it (observed on this hardware):**
- Back-to-back POWERDOWN + RESET commands, especially in a loop
  ("revive storms"). Even a freshly power-cycled chip can be killed by an
  aggressive 3× (PD + double-reset) sequence.
- Sustained mis-timed SPI at turbo rates.

**What does NOT fix it (all tried and failed):**
- Repeated RESET commands (1–6×), POWERDOWN + long idle, reconfiguring
  rates, closing/reopening SPI.

**The only reliable fix:**
1. **Full power cycle of the board** (remove 3.3 V from the ADS1220, wait
   a few seconds, reapply). A Pi reboot is enough if the board is powered
   from the Pi rail — but if the board has an independent supply, that
   supply must actually drop.
2. After power-up: wait ≥ 1 s, then a single gentle `reset()` **or** go
   straight to a config write (both have worked post power-cycle).
3. Verify with `selftest` before proceeding.

**How to avoid it:**
- One reset per power-on, at most.
- Never loop `powerdown()`+`reset()` as a "revive" — it makes things worse.
- Change rates/modes through `set_config()` only -- it resets the part before each write (a raw second WREG can be dropped, leaving the ADC stuck at the previous rate).
- Keep SCLK ≤ 300 kHz in turbo.

## A safe diagnostic sequence

When something looks wrong, run this (it uses no resets and won't worsen
a desync):

```python
import time
from ads1220 import ADS1220
adc = ADS1220(sclk_hz=300_000)

# 1) is anything alive? gentle config write only (no RESET):
adc._wr(0, 0x00)          # REG0: AIN0-AIN1, gain 1
adc._wr(1, 0x06)          # REG1: 20 SPS normal, continuous, temp
adc.start_sync()
time.sleep(1.5)

# 2) temperature oracle:
try:
    print("temp:", adc.read_temp())      # sane 10..40 C -> ALIVE, decode OK
except Exception as e:
    print("no data:", e)                 # -> likely desynced

# 3) DRDY health:
try:
    print("rate:", round(adc.drdy_rate(2.0)), "Hz")   # ~23 Hz -> DRDY clean
except Exception as e:
    print("DRDY problem:", e)           # stuck/flaky -> power-cycle

adc.powerdown(); adc.close()
```

## Still stuck?

- Re-verify the wiring table (MOSI/MISO roles) with the 20 SPS temperature
  oracle — it is the fastest end-to-end test (SPI + config + decode).
- Scope/measure DRDY (GPIO 25): it should toggle at the set rate; constant
  LOW or HIGH both indicate desync/wiring.
- Measure SCLK (GPIO 11): mode 1 means the clock is LOW when CS is idle.
- Consult the TI datasheet SBAS501, §8.4 (SPI protocol) and Table 8-4
  (conversion times).
