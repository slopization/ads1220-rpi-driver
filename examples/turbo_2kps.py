#!/usr/bin/env python3
"""2 kSPS turbo mode demo.

IMPORTANT: turbo mode requires SCLK <= 300 kHz (internal oscillator
start-up requirement), so this example lowers the SPI clock.

Single-shot reads (START -> DRDY edge -> RDATA) are used because they
keep a constant SCLK phase and decode cleanly at high rate.
"""
import time

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ads1220 import ADS1220

with ADS1220(sclk_hz=300_000) as adc:
    adc.reset()

    # measure the real DRDY rate (internal oscillator runs a bit fast,
    # so expect ~2.3 kSPS rather than exactly 2000)
    adc.set_config(2000, "turbo", ts=True)
    time.sleep(1.0)
    print(f"measured DRDY rate: {adc.drdy_rate(3.0):.0f} SPS (nominal 2000)")

    # temperature oracle at 2 kSPS (should match the 20 SPS value)
    temps = [adc.decode_temp(adc.single_shot()) for _ in range(12)]
    temps = [t for t in temps if -10 < t < 95]
    print(f"temp @ 2kSPS: {sum(temps)/len(temps):.2f} C "
          f"(std {(__import__('statistics').pstdev(temps)):.3f} C, n={len(temps)})")

    # AIN0-AIN1 at 2 kSPS
    adc.set_config(2000, "turbo", mux=0, gain=1)
    vs = [adc.decode_24bit(adc.single_shot()) * 2.048 / (1 << 23) * 1000
          for _ in range(12)]
    print(f"AIN0-AIN1 @2kSPS: {sum(vs)/len(vs):+.3f} mV "
          f"(std {(__import__('statistics').pstdev(vs)):.3f} mV)")
