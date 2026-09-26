# 1. Wiring

## Pinout (verified on the CJMCU-1220)

| ADS1220 pin | Function        | RPi GPIO | RPi SPI role |
|-------------|-----------------|----------|--------------|
| DIN         | SPI CS0         | GPIO 8   | CE0 (chip select) |
| CLK         | SPI clock       | GPIO 11  | SCLK |
| DOUT        | data out (ADC→Pi) | GPIO 9 | MISO |
| CS          | data in (Pi→ADC)  | GPIO 10  | MOSI |
| DRDY        | data ready (active LOW) | GPIO 25 | — |

Also required (present on the CJMCU-1220):

| ADS1220 pin | Connection |
|-------------|-----------|
| AVDD / DVDD / AREF | 3.3 V (CJMCU-1220 has an on-board regulator) |
| AVSS / DGND / REF | GND |
| AIN0–AIN3 | sensor inputs (differential pairs) |

> This build uses the **internal reference (2.048 V)** and the **internal
> oscillator** — no external REF or XCLK wiring is needed.

## The MOSI/MISO naming trap

The ADS1220 datasheet labels its SPI pins from the **device's** point of
view, which reads backwards to most people:

- **CS** on the ADS1220 = **MOSI** in RPi terms = carries Pi→ADC data
- **DOUT** on the ADS1220 = **MISO** in RPi terms = carries ADC→Pi data

If you wired from the CJMCU-1220 silkscreen and see "no data / 0xFF",
suspect a swapped data pair. **But check it properly first**: a swapped
pair gives exactly the same symptom as a desynced chip. The reliable
wiring test is the **20 SPS temperature oracle** — if you get a stable,
real temperature, the wiring is correct and don't swap anything.

## Power

- The ADS1220 draws ~6 mA in normal mode, ~12 mA turbo; any 3.3 V source
  that handles 50 mA is fine.
- The chip powers from the RPi's rail; it survives Pi reboots but **not**
  its desynced state (see [08-troubleshooting](08-troubleshooting.md)).
- Keep the GND between the RPi and the sensor circuit common.

## Enabling SPI on the RPi

```bash
# most recent Pi OS images have SPI enabled; otherwise:
sudo raspi-config
#   → Interface Options → SPI → <Y> to enable
# then:
sudo reboot
# verify:
ls /dev/spidev0.0
```

GPIO access via the gpiod library needs no extra setup — the `pi` user and
the default `spi` group are sufficient.

## Signal integrity

- Keep the SPI traces under ~10 cm for 300–500 kHz (they are; the CJMCU-1220
  is typically held right next to the header).
- SCLK above ~500 kHz is not supported by this driver — the part itself
  wants a 10× margin (SCLK ≫ fMOD) and the internal oscillator adds jitter.
