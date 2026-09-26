"""ads1220 -- Raspberry Pi driver for the TI ADS1220 24-bit ADC.

Verified on a Raspberry Pi 4B with a CJMCU-1220 ADS1220 breakout board:

    ADS1220 pin      RPi GPIO
    -------------------------
    DIN (CS0)  ->   GPIO 8   (CE0)
    CLK (SCLK) ->   GPIO 11
    DOUT (MISO)->   GPIO 9
    CS  (MOSI) ->   GPIO 10
    DRDY       ->   GPIO 25

Quick start::

    from ads1220 import ADS1220

    with ADS1220() as adc:
        adc.reset()
        adc.set_config(20, "normal", ts=True)   # 20 SPS temperature
        print(f"{adc.read_temp():.2f} C")

        # 2 kSPS (turbo) -- use a lower SCLK for turbo
        adc.set_config(2000, "turbo")
        raw = adc.single_shot()
        print(adc.decode_24bit(raw))

See README.md for wiring, rate tables, decoding, and troubleshooting.
"""
from ._driver import (
    ADS1220,
    ADS1220Error,
    ConfigError,
    MUXES,
    GAINS,
    DATA_RATES,
    __version__,
)

__all__ = [
    "ADS1220",
    "ADS1220Error",
    "ConfigError",
    "MUXES",
    "GAINS",
    "DATA_RATES",
    "__version__",
]
