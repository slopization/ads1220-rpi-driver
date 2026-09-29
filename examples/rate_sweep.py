#!/usr/bin/env python3
"""Sweep all data rates and verify the measured DRDY rate at each.

set_config() resets the part before every rate change (the part does
not reliably accept consecutive config writes). SCLK is lowered for
turbo.
"""
import time

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ads1220 import ADS1220, DATA_RATES

print(f"{'mode':8s} {'nominal':>8s} {'measured':>9s}  status")
print("-" * 42)

with ADS1220(sclk_hz=300_000) as adc:
    adc.reset()
    for mode in ("normal", "turbo"):
        for i, sps in enumerate(DATA_RATES[mode]):
            adc.set_config(i, mode)          # DR index i
            time.sleep(0.5)
            try:
                measured = adc.drdy_rate(1.0 if sps >= 300 else 2.0)
            except Exception as e:
                print(f"{mode:8s} {sps:>8.0f} {'ERR':>9s}  {e}")
                continue
            ratio = measured / sps
            status = "ok" if 0.8 < ratio < 1.3 else "CHECK"
            print(f"{mode:8s} {sps:>8.0f} {measured:>9.0f}  {status}")
