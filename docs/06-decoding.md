# 6. Decoding

All math below is **verified against this hardware** (temperature oracle,
exact 1/gain AIN scaling, 2 kSPS cross-check).

## 24-bit framing

`RDATA` clocks out 4 bytes: `b0 b1 b2 b3`. The ADS1220 shifts DOUT one bit
early on the first CS pulse, so the 24-bit word is **not** a naive
`b0<<16|b1<<8|b2`. The verified combination:

```python
W = ((b0 & 0x7F) << 17) | (b1 << 9) | (b2 << 1) | (b3 >> 7)
# signed: if W >= 0x800_000: W -= 0x1000_0000
```

This is `ADS1220.decode_24bit(raw)`. The one-bit offset is a property of
the DOUT shifting, not of our wiring — it is stable for a fixed
transaction sequence (which `single_shot()` guarantees).

| Raw frame | W | Comment |
|-----------|---|---------|
| `FF FF FF FF` | — | **sentinel**: no valid data (conversion pending / desync) |
| `87 0F FF FF` | +925 695 | temp = 28.219 °C (oracle frame) |
| `87 0F F8 FF` | +925 681 | temp = 28.219 °C |

## Voltage

```
V_in = W * VREF / gain / 2^23
```

- `VREF = 2.048 V` (internal reference, full scale ±2.048 V at gain 1)
- `gain` = the PGA gain the signal went through (must match `set_config`)
- Result is in volts (differential, AINP − AINN)

Sanity anchors (verified): shorting AIN0=AIN1 gives W≈0; a 100 mV step at
gain 1 reads 100.0 mV ± noise; at gain 8 the same step reads 100.0 mV with
8× smaller code noise (exact 1/gain scaling).

## Temperature (internal sensor)

Configure with `ts=True` (REG1 bit 1). With TS enabled the device uses its
internal reference and ignores REG0 mux/gain.

The 14-bit temperature code lives in the **top 14 bits** of the 24-bit
result (bits [23:10] of W), two's complement, LSB = 0.03125 °C:

```python
t14 = (W >> 10) & 0x3FFF
if t14 >= 0x2000: t14 -= 0x4000      # two's complement
T = t14 * 0.03125                    # degrees C
```

Range: −128…+127.97 °C, resolution 0.03125 °C.

Verified oracle points: 24.2 °C (room), 28.2 °C (heated), 48.5 °C
(hotter) — all clean at both 20 SPS and 2 kSPS (std < 0.1 °C at 2 kSPS).

## Don't-care / noise bits

The low bits of the temperature code (and the LSBs of low-gain AIN codes)
are "don't care" per the datasheet and wander; that is why single-frame
temperature can jump by 1–2 LSBs between reads even at std ≈ 0. Average a
handful of samples for a stable number.

## Frame validity checks (used by the driver)

- `b0 == 0xFF` for all four bytes → `ADS1220Error` (no data / desync).
- Temperature filtered to −10…95 °C in aggregate reads (rejects corrupted
  frames).
- Voltage filtered to −2.048…+2.048 V / gain in aggregate reads.
