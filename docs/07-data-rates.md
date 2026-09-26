# 7. Data Rates

All rates (datasheet Table 8-12, computed for the 4.096 MHz clock). With the
**internal oscillator** (no external XCLK wired) the actual rate runs
slightly fast — expect ~+10–15 % (20 SPS → ~23 Hz, 2000 SPS → ~2300 Hz).

## Rate tables

| DR | Normal (256 kHz) | Duty-cycle (1:4) | Turbo (512 kHz) |
|----|------------------|------------------|-----------------|
| 0  | 20 SPS           | 5 SPS            | 40 SPS          |
| 1  | 45 SPS           | 11.25 SPS        | 90 SPS          |
| 2  | 90 SPS           | 22.5 SPS         | 180 SPS         |
| 3  | 175 SPS          | 44 SPS           | 350 SPS         |
| 4  | 330 SPS          | 82.5 SPS         | 660 SPS         |
| 5  | 600 SPS          | 150 SPS          | 1200 SPS        |
| 6  | 1000 SPS         | 250 SPS          | **2000 SPS**    |

`DATA_RATES[mode]` in the driver returns the per-mode tuple in DR order.

## How to address a rate

`set_config(sps, mode, …)` accepts either form:

```python
adc.set_config(2000, "turbo")    # by nominal SPS value (preferred)
adc.set_config(6, "turbo")       # by DR index (0..6)
adc.set_config(20.0, "normal")   # floats are rounded to the table value
```

A value not in the table raises `ConfigError` listing the valid choices.

## Conversion time per rate

Conversion time = filter settling in tCLK units (datasheet Table 8-4).
Key values at 4.096 MHz:

| Rate | tCLK per conversion | Time (nominal) |
|------|--------------------:|---------------:|
| 20 SPS (normal) | 204 768 | ~42 ms |
| 1000 SPS (normal) | 4 096 | ~0.82 ms |
| 2000 SPS (turbo) | 967.6 | ~0.24 ms |

Measured on this hardware (internal oscillator): 20 SPS → **42.04 ms**,
2000 SPS → **0.43 ms** (~2320 Hz).

## Rate-change procedure

```python
adc.set_config(660, "turbo")     # one register write — done
```

- A WREG of REG1 **restarts the conversion** (datasheet §8.4.2.2); the new
  rate is active from the next DRDY cycle. No RESET, no powerdown.
- After a mode change normal↔turbo, allow a few cycles before reading
  (the filter re-settles; a 0.5 s `sleep` is plenty for ≤1 kSPS).
- SCLK must be lowered to ≤ 300 kHz **before** entering turbo
  (`ADS1220(sclk_hz=300_000)`).

## Reading at each rate

| Rate range | Recommended read pattern |
|------------|--------------------------|
| ≤ 350 SPS (normal/duty) | continuous mode + `wait_drdy()` + `read_raw()`, or blind RDATA polling at >5× the rate is risky — use `wait_drdy()` |
| 350–1000 SPS | continuous + `stream(n)` (driver waits per frame) |
| ≥ 1200 SPS (turbo) | **`single_shot()`** (START→edge→RDATA) — blind polling aliases badly; DRDY low-window is <0.5 ms |

`single_shot()` works at **every** rate and is the recommended read for
accuracy; the only cost is the extra START transaction per sample.

## Measuring the real rate

Use `drdy_rate()` — it uses kernel hardware edge timestamps on DRDY and is
robust up to and beyond 2 kSPS. Two things that give **wrong** numbers:

1. **Counting fresh DOUT frames** — the DOUT pattern changes on every
   RDATA poll, so dedup-based counters saturate at the read-loop speed
   (~1450/s) regardless of the true rate.
2. **Value-polling DRDY** — at 2 kSPS the low-window is ~250–500 µs; a
   Python poll loop catches only 30–50 % of cycles → a ~10× aliased
   reading (~200 Hz instead of 2000).
