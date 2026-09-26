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
        t = adc.read_temp()
        print(f"sample {i}: {t:.2f} C")
