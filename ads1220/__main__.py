"""Command-line entry point.

Usage:
    python -m ads1220 selftest
    python -m ads1220 temp [n]
    python -m ads1220 ain [gain] [sps]
    python -m ads1220 rate [mode] [sps]
    python -m ads1220 pga
"""
from __future__ import annotations

import sys

from . import ADS1220
from ._driver import DATA_RATES


def _adc(mode):
    # turbo needs a lower SCLK (internal oscillator start-up requirement)
    return ADS1220(sclk_hz=300_000 if mode == "turbo" else 400_000)


def selftest():
    with _adc("normal") as adc:
        r = adc.selftest()
        print(r)


def temp(n=5):
    with _adc("normal") as adc:
        adc.reset()
        adc.set_config(20, "normal", ts=True)
        import time
        time.sleep(1.0)
        for i in range(n):
            print(f"sample {i}: {adc.read_temp():.2f} C")
            time.sleep(0.06)


def ain(gain=1, sps=90):
    with _adc("normal") as adc:
        adc.reset()
        adc.set_config(sps, "normal", mux=0, gain=gain)
        import time
        time.sleep(0.5)
        for i in range(10):
            print(f"sample {i}: {adc.read_voltage(gain=gain)*1000:+.3f} mV")
            time.sleep(1.0 / sps)


def rate(mode="normal", sps=2000):
    with _adc(mode) as adc:
        adc.reset()
        adc.set_config(sps, mode)
        import time
        time.sleep(1.0)
        print(f"{mode} {sps} SPS -> measured {adc.drdy_rate(3.0):.0f} SPS")


def pga():
    with _adc("normal") as adc:
        r = adc.pga_test()
        print("gain   code         V (mV)   std (mV)   ok")
        for g, d in r["per_gain"].items():
            if "reason" in d:
                print(f"g{g:<5d} {d['reason']}")
            else:
                print(f"g{g:<5d} {d['code']:+12.0f} {d['v_mV']:+10.3f} "
                      f"{d['std_mV']:>10.3f}   {'OK' if d['ok'] else 'FAIL'}")
        print(f"PGA TEST: {'PASS' if r['pass'] else 'FAIL'}")


def main(argv):
    if len(argv) >= 2 and argv[1] == "selftest":
        selftest()
    elif len(argv) >= 2 and argv[1] == "temp":
        temp(int(argv[2]) if len(argv) > 2 else 5)
    elif len(argv) >= 2 and argv[1] == "ain":
        ain(int(argv[2]) if len(argv) > 2 else 1,
            int(argv[3]) if len(argv) > 3 else 90)
    elif len(argv) >= 2 and argv[1] == "pga":
        pga()
    elif len(argv) >= 2 and argv[1] == "rate":
        mode = argv[2] if len(argv) > 2 else "turbo"
        sps = int(argv[3]) if len(argv) > 3 else DATA_RATES[mode][-1]
        rate(mode, sps)
    else:
        print(__doc__)
        print("DATA_RATES:", DATA_RATES)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
