#!/usr/bin/env python3
"""Basic demo: internal temperature at 20 SPS (normal mode)."""
import time

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ads1220 import ADS1220

with ADS1220() as adc:
    adc.reset()                                   # once at startup
    adc.set_config(20, "normal", ts=True)         # 20 SPS temperature
    time.sleep(1.0)
    for i in range(5):
        # sync each read to the DRDY falling edge; a blind RDATA can
        # land mid-conversion and read 0xFF FF FF FF
        raw = adc.single_shot(timeout_s=0.1)
        t = adc.decode_temp(raw)
        print(f"sample {i}: {t:.2f} C")
