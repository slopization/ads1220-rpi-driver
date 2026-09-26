# 2. Installation

## Dependencies

Two small packages (both in Raspberry Pi OS's apt repo):

```bash
sudo apt update
sudo apt install python3-spidev python3-gpiod
```

or via pip (Python 3.9+):

```bash
pip3 install spidev gpiod
```

| Package | Why |
|---------|-----|
| `spidev`  | userspace SPI (`/dev/spidev0.0`) |
| `gpiod`   | Linux GPIO chardev v2 API (DRDY) |

No kernel modules, no device-tree changes, no C code to compile.

## Installing the library

The folder **is** the package. Put it anywhere and point Python at it:

```bash
# option A: run scripts from inside the folder
cd ~/ads1220-rpi-driver
python3 examples/basic_temp.py

# option B: make it importable from anywhere (per-user)
echo 'export PYTHONPATH=$HOME/ads1220-rpi-driver:$PYTHONPATH' >> ~/.bashrc
source ~/.bashrc
python3 -c 'from ads1220 import ADS1220; print("ok")'

# option C: install it into site-packages
pip3 install --user -e ~/ads1220-rpi-driver   # needs a pyproject/setup;
                                               # otherwise just copy ads1220/
                                               # into ~/.local/lib/python3.x/site-packages
```

The `examples/` scripts work out of the box when run from the folder root
because they do a `sys.path` insert themselves.

## First check

```bash
cd ~/ads1220-rpi-driver
python3 -m ads1220 selftest
# expected (device healthy):
# {'temp_c': 24.xx, 'temp_std': 0.00x, 'n_samples': 10, 'rate_hz': 23, 'rate_nominal': 20.0}
```

- `temp_c` in the real room range (≈10–40 °C) with `temp_std` < 0.5 →
  **wiring + decoding verified**.
- `rate_hz` ≈ 20 → DRDY wiring + rate meter verified.
- `rate_hz: 'n/a …'` but good temp → see the desync section in
  [08-troubleshooting](08-troubleshooting.md).
