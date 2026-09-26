#!/usr/bin/env python3
"""PGA / gain-chain verification using MUX 14 (known 0 V differential).

MUX 14 shorts AINP and AINN to (AVDD+AVSS)/2, so the differential input is
guaranteed 0 V: at every gain the decoded voltage must be ~0 mV and the
raw code must not saturate. No external signal needed.

Also demonstrates the PGA_BYPASS bit (only meaningful at gains 1/2/4).
"""
import time

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ads1220 import ADS1220

with ADS1220() as adc:
    r = adc.pga_test()
    print("gain   code         V (mV)   std (mV)   ok")
    for g, d in r["per_gain"].items():
        if "reason" in d:
            print(f"g{g:<5d} {d['reason']}")
        else:
            print(f"g{g:<5d} {d['code']:+12.0f} {d['v_mV']:+10.3f} "
                  f"{d['std_mV']:>10.3f}   {'OK' if d['ok'] else 'FAIL'}")
    print(f"\nPGA TEST: {'PASS' if r['pass'] else 'FAIL'}")

    # PGA_BYPASS demo at gain 1 (switched-capacitor stage, wider CM range)
    adc.set_config(90, "normal", mux=0, gain=1, pga_bypass=True)
    time.sleep(0.5)
    print("\nPGA_BYPASS=True @ g1 AIN0-AIN1: "
          f"{adc.read_voltage(gain=1) * 1000:+.2f} mV")
