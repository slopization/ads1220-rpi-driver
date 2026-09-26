# 5. SPI Protocol & Registers

Reference for register-level debugging. The driver uses SPI **mode 1**
(CPOL=0, CPHA=1). All transactions are clocked out by the RPi; DOUT shifts
out **continuously** (no CS gating) and is read after the first CS pulse.

## Command opcodes

The first byte of every SPI transaction is a command. The WREG/RREG
opcodes carry the 2-bit register address in bits [1:0]:

| Opcode | Command | Payload | Effect |
|--------|---------|---------|--------|
| `0x02` | POWERDOWN | — | low-power state |
| `0x06` | RESET | — | full soft reset |
| `0x08` | START / SYNC | — | start a conversion (single-shot) or restart the pipeline (continuous) |
| `0x10` | RDATA | 3 dummy bytes | shift out the 24-bit result (4 bytes total) |
| `0x40 \| reg<<2` | WREG | 1 value byte | write register `reg` (0–3) |
| `0x20 \| reg<<2` | RREG | 1 dummy byte | read register `reg` (echo) |

**A WREG of any configuration register restarts the in-flight conversion**
(datasheet §8.4.2.2) — that is why this driver changes rate with a plain
write and never resets.

## Register map (SPI mode)

### REG0 (`0x40`, reset `0x00`) — input configuration

| Bits | Field | Notes |
|------|-------|-------|
| 7:4 | MUX[3:0] | input multiplexer; see `MUXES` |
| 3:1 | GAIN[2:0] | `000`=1, `001`=2, `010`=4, `011`=8, …, `111`=128 |
| 0 | PGA_BYPASS | see below |

Driver builds it as `reg0 = (mux & 0x0F) << 4 | GAINS.index(gain) << 1 | int(pga_bypass)`.

**PGA_BYPASS semantics** (datasheet §6.2 / Table 8-10):

* Gains 1/2/4: `PGA_BYPASS=1` disables the low-noise PGA; a buffered
  switched-capacitor stage provides the gain. Wider absolute/common-mode
  input range (AVSS−0.1 V … AVDD+0.1 V), lower power.
* Gains ≥ 8: the bit is **ignored** — the PGA is always enabled.
* Muxes 8–13 (AINx–AVSS single-ended, VREF/4 and AVDD/4 monitors): the
  PGA **must** be bypassed AND only gains 1/2/4 are allowed. The driver
  enforces both (forces the bit on, rejects the other settings).

MUX values (driver `MUXES`):

| idx | AINP | AINN | Note |
|-----|------|------|------|
| 0 | AIN0 | AIN1 | default differential |
| 1 | AIN0 | AIN2 | |
| 2 | AIN0 | AIN3 | |
| 3 | AIN1 | AIN2 | |
| 4 | AIN1 | AIN3 | |
| 5 | AIN2 | AIN3 | |
| 6 | AIN1 | AIN0 | |
| 7 | AIN3 | AIN2 | |
| 8–11 | AIN0–3 | AVSS | single-ended; **gain 1/2/4 only** |
| 12 | (VREFP−VREFN)/4 | — | monitor |
| 13 | (AVDD−AVSS)/4 | — | supply monitor |
| 14 | (AVDD+AVSS)/2 | shorted | self-test |

### REG1 (`0x44`, reset `0x06`) — conversion configuration

| Bits | Field | Values |
|------|-------|--------|
| 7:5 | DR[2:0] | data-rate index 0–6 (see [07-data-rates](07-data-rates.md)) |
| 4:3 | MODE[1:0] | `00` normal (256 kHz), `01` duty-cycle, `10` **turbo (512 kHz)**, `11` reserved |
| 2 | CM | `0` single-shot, `1` continuous |
| 1 | TS | `1` enables the internal temperature sensor (REG0 ignored then) |
| 0 | BCS | `1` enables 10 µA burn-out current sources |

Layout: `REG1 = (DR << 5) | (MODE << 3) | (CM << 2) | (TS << 1) | BCS`

Common values (hardware-verified):

| Setting | REG1 |
|---------|------|
| 20 SPS normal, continuous, AIN | `0x04` |
| 20 SPS normal, continuous, temp | `0x06` |
| 2 kSPS turbo, continuous, AIN | `0xD4` |
| 2 kSPS turbo, continuous, temp | `0xD6` |
| 2 kSPS turbo, single-shot, temp | `0xD2` |

### REG2 (`0x48`, reset `0x00`) — VREF / IDAC

Programming of the internal reference and the IDAC current sources. This
driver leaves it at reset default.

### REG3 (`0x4C`, reset `0x00`)

Reserved / device ID region. Left at reset default.

## Timing (datasheet-relevant)

| Item | Value | Note |
|------|-------|------|
| SCLK max (normal) | ~500 kHz | driver default 400 kHz |
| SCLK max (turbo) | **≤ 300 kHz** | internal oscillator start-up requirement (verified: corrupt results at 500 kHz) |
| tCLK (t0/t1) | datasheet Figure 8-65 | first CS pulse must start before the 2nd bit shifts out |
| DRDY pulse width | ≥ a few tCLK | safe to poll at µs resolution |
| 20 SPS conversion | 204 768 tCLK | ~42 ms measured (internal osc runs fast) |
| 2 kSPS turbo conversion | 967.6 tCLK | ~0.43 ms measured → ~2.3 kSPS |

## DRDY

Active-**low** open-drain: LOW = a fresh 24-bit result is available in the
DOUT register. Two useful properties verified on hardware:

1. The falling edge is **kernel hardware-timestamped** by gpiod → the only
   reliable way to measure rate at high rates.
2. The LOW window at 2 kSPS is sub-millisecond → reads must be triggered
   by the edge (or tight value-polling), never by a fixed sleep.
