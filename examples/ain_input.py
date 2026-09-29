#!/usr/bin/env python3
"""Read the AIN0-AIN1 differential input at 90 SPS (normal mode).

Connect a signal between AIN0 (positive) and AIN1 (negative).
With the internal 2.048 V reference and gain 1 the full-scale range is
+/-2.048 V; use a higher gain for small signals.
"""
import time

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ads1220 import ADS1220

GAIN = 16
RATE = 90   # SPS (normal mode)

with ADS1220() as adc:
    adc.reset()
    adc.set_config(RATE, "normal", mux=0, gain=GAIN)  # AIN0-AIN1
    time.sleep(0.5)
    for i in range(10):
        # sync each read to the DRDY falling edge; a blind RDATA can
        # land mid-conversion and read 0xFF FF FF FF
        raw = adc.single_shot(timeout_s=0.02)
        v = adc.decode_24bit(raw) * 2.048 / GAIN / (1 << 23) * 1000
        print(f"sample {i}: {v:+.3f} mV")
