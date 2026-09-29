# 3. Quick Start

Everything below runs from the folder root: `cd ~/ads1220-rpi-driver`.

## Read the internal temperature (2 minutes)

```python
from ads1220 import ADS1220
import time

with ADS1220() as adc:
    adc.set_config(20, "normal", ts=True)   # 20 SPS temperature
    time.sleep(1.0)
    for _ in range(5):
        print(f"{adc.read_temp():.2f} C")
        time.sleep(0.06)
```

Or from the CLI:

```bash
python3 -m ads1220 temp        # 5 samples @ 20 SPS
python3 -m ads1220 selftest    # health check
```

## Read a differential input

```python
with ADS1220() as adc:
    adc.set_config(90, "normal", mux=0, gain=16)   # AIN0−AIN1, ×16, 90 SPS
    time.sleep(0.5)
    v = adc.read_voltage(gain=16) * 1000
    print(f"{v:+.3f} mV")
```

`mux` selects the pair (see `MUXES`): `0` AIN0−AIN1, `3` AIN1−AIN2, `5`
AIN2−AIN3, … `8` AIN0−AVSS (single-ended, gain 1/2/4 only).

## Go to 2 kSPS (turbo)

```python
from ads1220 import ADS1220
import time

# turbo mode wants SCLK <= 300 kHz
with ADS1220(sclk_hz=300_000) as adc:
    adc.set_config(2000, "turbo", ts=True)
    time.sleep(1.0)

    print(f"measured rate: {adc.drdy_rate(3.0):.0f} SPS   # ~2300 (internal osc)")
    print(f"temp @ 2kSPS : {adc.read_temp():.2f} C")
```

Or the ready-made script: `python3 examples/turbo_2kps.py`.

## Change rate without a reset

```python
with ADS1220(sclk_hz=300_000) as adc:
    adc.set_config(40, "turbo")      # DR index or SPS value
    adc.set_config(660, "turbo")     # safe: set_config() resets the part first
    adc.set_sps(2000)                # or: keep mux/gain/ts, change rate
```

## PGA / gain check

```python
r = adc.pga_test()            # MUX14 known-0V oracle, gains 1..128
print(r["pass"])              # True = gain chain verified
```

or `python3 -m ads1220 pga`.

## CLI summary

```bash
python3 -m ads1220 selftest                 # health check (temp + rate)
python3 -m ads1220 temp [n]                 # n temperature samples @ 20 SPS
python3 -m ads1220 ain [gain] [sps]         # AIN0-AIN1 voltage
python3 -m ads1220 rate [mode] [sps]        # measure a specific rate
python3 -m ads1220 pga                       # PGA / gain-chain check
```
