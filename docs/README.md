# ads1220-rpi-driver — Documentation

Raspberry Pi driver for the **TI ADS1220** 24-bit delta-sigma ADC.
Verified on a Raspberry Pi 4B with a CJMCU-1220 ADS1220 breakout board.

## Contents

| Doc | What it covers |
|-----|----------------|
| [01-wiring](01-wiring.md) | Pinout, SPI roles, MOSI/MISO clarification, power, enabling SPI |
| [02-installation](02-installation.md) | Dependencies, installing the package, first check |
| [03-quickstart](03-quickstart.md) | Five-minute temperature & AIN examples |
| [04-api-reference](04-api-reference.md) | Full reference for `ADS1220` and helpers |
| [05-protocol-and-registers](05-protocol-and-registers.md) | SPI commands, register map, timing |
| [06-decoding](06-decoding.md) | 24-bit framing, voltage, and temperature math |
| [07-data-rates](07-data-rates.md) | All 14 rates, modes, and measurement caveats |
| [08-troubleshooting](08-troubleshooting.md) | Symptom → cause → fix, plus the desync protocol |

## What makes this driver different

The ADS1220 is an unforgiving part: the wrong SPI mode, the wrong SCLK, or a
burst of resets will put it into a "desynced" state that only a full power
cycle clears. This driver encodes the verified-good behaviour:

1. **SPI mode 1 only** (CPOL=0, CPHA=1).
2. **SCLK ≤ 300 kHz in turbo mode** (internal-oscillator start-up limit).
3. **A reset before each rate change.** A config write restarts the
   conversion (datasheet §8.4.2.2), but the part does not reliably
   accept consecutive config writes — a dropped second WREG leaves the
   ADC stuck at the previous rate. `set_config()` performs the reset.
4. **Single-shot reads at high rate** (START → DRDY edge → RDATA) so the
   SCLK phase is constant and the 24-bit framing stays stable.
5. **Hardware-timestamped DRDY rate meter** (immune to the aliasing and
   ring-overflow artefacts that plague polling-based counting).
6. **Gentle lifecycle** — resets are opt-in, not the default.

## Verification status

| Capability | Status | Evidence |
|------------|--------|----------|
| 20 SPS normal temp | ✅ verified | oracle 24–28 °C, std < 0.05 °C |
| 2 kSPS turbo temp | ✅ verified | 24.22 °C vs 20 SPS ref in same run (Δ 0.03 °C) |
| 2 kSPS turbo rate | ✅ verified | DRDY 2320–2362 SPS (nominal 2000) |
| AIN gain scaling | ✅ verified | exact 1/gain across g1/8/16/32 |
| PGA bypass bit | ✅ verified | forced for mux 8–13; ignored at g≥8; `pga_test()` PASS g1–g128 |
| AIN-path monitor mux 14 | ✅ verified | stable 0 V-diff oracle across g1–g128 (`pga_test`) |
| On-chip monitors 12/13 | ⚠️ works, odd values | CJMCU-1220 quirk — see README "Inputs" note |
| Full 14-rate sweep | ✅ library support | `examples/rate_sweep.py` |
