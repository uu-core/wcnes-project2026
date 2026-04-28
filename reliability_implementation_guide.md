# Pico Backscatter — Reliability Optimisation
## Implementation Documentation & Experiment Guide
*WCNES Project 2026*

---

## 1. Overview

This document describes two reliability optimisations implemented for the Pico Backscatter communication system: **Hamming(7,4) Forward Error Correction (FEC)** and **Block Interleaving**. Both are implemented in the firmware running on the Raspberry Pi Pico and can be enabled or disabled independently at compile time. The companion Python notebook contains all the analysis tools needed to measure and compare the Packet Error Rate (PER) across the three experimental configurations.

### 1.1 Why These Optimisations?

Analysis of baseline captures showed that bit errors in the backscatter channel tend to cluster into **bursts** — consecutive packets affected by the same fade or interference event. A single error-correcting code alone struggles with burst errors because a single codeword may receive more errors than it can correct. The two-stage approach addresses this:

- **FEC:** Hamming(7,4) can correct any single-bit error per 7-bit codeword.
- **Interleaving:** Block interleaving spreads a burst across many codewords so each codeword sees at most one error, putting it back within the correction capability of the FEC.

---

## 2. What Was Implemented

### 2.1 Hamming(7,4) FEC

Hamming(7,4) encodes every 4 data bits (one nibble) into a 7-bit codeword by adding 3 parity bits. The codeword layout is:

```
bit 6   bit 5   bit 4   bit 3   bit 2   bit 1   bit 0
  p1      p2      d1      p3      d2      d3      d4
```

Parity bits are computed as:

```
p1 = d1 ^ d2 ^ d4
p2 = d1 ^ d3 ^ d4
p3 = d2 ^ d3 ^ d4
```

On the receiver side, a syndrome is computed from the received codeword. A non-zero syndrome identifies the position of a single-bit error, which is then flipped to recover the original nibble. Two nibbles are packed per byte, so the encoded output is `DATA_LEN * 7 / 4` bytes for `DATA_LEN` data bytes.

> **Note:** The first 2 bytes of every packet (the pseudo-sequence number) are passed through unencoded — only the actual data payload is Hamming encoded.

### 2.2 Block Interleaving

Block interleaving uses a matrix of dimensions `INTERLEAVE_ROWS × INTERLEAVE_COLS` (64 × FEC_PAYLOADSIZE). The transmitter fills the matrix **row by row**, one FEC-encoded packet per row. Once all 64 rows are filled, it transmits the matrix **column by column** — each over-the-air packet carries one column (64 bytes, one byte from each of the 64 original packets).

A burst of errors affecting several consecutive over-the-air packets damages one byte in each of several columns. After de-interleaving on the receiver side, those damaged bytes are spread across 64 different original packets, so each original packet has at most one damaged byte — within the single-bit correction capability of Hamming(7,4).

> **Important:** When interleaving is enabled, each over-the-air packet carries `INTERLEAVE_ROWS = 64` bytes of payload (one full column), regardless of `DATA_LEN`. The notebook must be configured accordingly (`PAYLOADSIZE = 64`).

### 2.3 Configurable Build System

Three compile-time flags in `carrier-receiver-baseband/CMakeLists.txt` control the configuration. No source code changes are required between experiments — only the CMakeLists.txt values need to change.

| Flag | Values | Description |
|---|---|---|
| `DATA_LEN` | 12, 20, 52 | Number of data bytes per packet (excluding 2-byte pseudo-seq) |
| `USE_FEC` | 0 or 1 | 1 = enable Hamming(7,4) encoding; 0 = raw data |
| `USE_INTERLEAVING` | 0 or 1 | 1 = enable 64-packet block interleaving; 0 = direct transmit |

---

## 3. Files Changed / Added

| File | Status | Summary |
|---|---|---|
| `project_pico_libs/packet_generation.h` | Modified | `DATA_LEN` made configurable; `PAYLOADSIZE`, `FEC_PAYLOADSIZE`, `ACTIVE_PAYLOADSIZE` macros added; `add_header` updated to accept explicit `payload_len` |
| `project_pico_libs/packet_generation.c` | Modified | `add_header` implementation updated to use the passed `payload_len` instead of a hardcoded value |
| `project_pico_libs/fec.h` | New | Public header declaring `hamming_encode()` |
| `project_pico_libs/fec.c` | New | Hamming(7,4) encoder: `hamming_encode_nibble()` and `hamming_encode()` |
| `project_pico_libs/interleaver.h` | New | Declares `INTERLEAVE_ROWS` (64), `INTERLEAVE_COLS` (=FEC_PAYLOADSIZE), `interleave_block()`, `deinterleave_block()` |
| `project_pico_libs/interleaver.c` | New | `interleave_block()` fills one row of the matrix; `deinterleave_block()` reads one row back |
| `carrier-receiver-baseband/CMakeLists.txt` | Modified | Added `DATA_LEN`, `USE_FEC`, `USE_INTERLEAVING` compile definitions; added `fec.c` and `interleaver.c` as sources |
| `carrier-receiver-baseband/main.c` | Modified | `TX_BUF_PAYLOADSIZE` define added; static buffers resized; conditional FEC encode block (`#if USE_FEC`); conditional interleave block (`#if USE_INTERLEAVING`) with correct `INTERLEAVE_ROWS`-sized buffers and transmit loop |
| `stats/functions.py` | Modified | Added: `compute_per`, `byte_error_vector`, `hamming_decode_nibble`, `hamming_decode`, `compute_per_fec`, `deinterleave_block`, `compute_per_fec_interleaved` |
| `stats/statistics.ipynb` | Modified | Added: byte error distribution bar charts, FEC PER comparison cell, FEC + Interleaving PER cell |

---

## 4. How to Run the Experiments

Three firmware configurations are needed. Use the same physical setup for all three (same distance, same environment) so the results are comparable. The only thing that changes between runs is the CMakeLists.txt configuration and the log file name.

### Experiment 1 — Baseline (no FEC, no Interleaving)

**Step 1.** Open `carrier-receiver-baseband/CMakeLists.txt` and set:

```cmake
target_compile_definitions(carrier_receiver_baseband PRIVATE
    DATA_LEN=12
    USE_FEC=0
    USE_INTERLEAVING=0
)
```

**Step 2.** Build and flash to the Pico:

```bash
cd carrier-receiver-baseband/build
cmake .. && make -j4
# Copy the .uf2 file to the Pico (hold BOOTSEL while plugging in)
```

**Step 3.** Run the experiment and save the output log as a `.csv` file, e.g. `baseline_3m_rx25.csv`.

---

### Experiment 2 — FEC Only

**Step 1.** Change `CMakeLists.txt` to:

```cmake
target_compile_definitions(carrier_receiver_baseband PRIVATE
    DATA_LEN=12
    USE_FEC=1
    USE_INTERLEAVING=0
)
```

**Step 2.** Rebuild, flash, and capture. Save as e.g. `fec_3m_rx25.csv`.

> **Note:** With FEC enabled the encoded payload is `DATA_LEN * 7 / 4 + 2` bytes. For `DATA_LEN=12` that is 23 bytes per packet — set `PAYLOADSIZE = 23` in the notebook for this capture.

---

### Experiment 3 — FEC + Interleaving

**Step 1.** Change `CMakeLists.txt` to:

```cmake
target_compile_definitions(carrier_receiver_baseband PRIVATE
    DATA_LEN=12
    USE_FEC=1
    USE_INTERLEAVING=1
)
```

**Step 2.** Rebuild, flash, and capture. Save as e.g. `fec_il_3m_rx25.csv`.

> **Note:** With interleaving enabled the over-the-air packet carries `INTERLEAVE_ROWS = 64` bytes of payload. Set `PAYLOADSIZE = 64` in the notebook for this capture.

> **Important:** The interleaver accumulates 64 packets before transmitting, so the first transmission is delayed by `64 × TX_DURATION ms` (~16 seconds at 250 ms/packet). Allow enough capture time to collect at least a few complete blocks.

---

## 5. Analysing Results in the Notebook

Open `stats/statistics.ipynb`. For each capture file:

**Step 1.** Set the filename and payload size at the top of the notebook:

```python
filename    = "fec_il_3m_rx25"   # no .csv extension
PAYLOADSIZE = 64                  # see table below
```

| Configuration | PAYLOADSIZE in notebook |
|---|---|
| Baseline or FEC only, DATA_LEN=12 | 14 |
| Baseline or FEC only, DATA_LEN=20 | 22 |
| Baseline or FEC only, DATA_LEN=52 | 54 |
| FEC + Interleaving (any DATA_LEN) | 64 |

**Tip:** Run this diagnostic cell to confirm the payload length before setting `PAYLOADSIZE`:

```python
df['payload_len'] = df.payload.apply(lambda x: (len(x) + 1) // 3)
print(df['payload_len'].value_counts())
```

**Step 2.** Run all cells in order. The notebook will produce:

- BER and data rate (existing cells)
- Byte error distribution bar charts
- PER without FEC decoding vs PER with FEC decoding (FEC-only capture)
- PER after de-interleaving and FEC decoding (FEC+IL capture)

**Step 3.** Record the PER values for each configuration and distance setting to build your comparison table.

---

## 6. Payload Size Reference

The table below shows how packet sizes grow through each processing stage. All sizes are in bytes.

| DATA_LEN | PAYLOADSIZE (baseline) | FEC_PAYLOADSIZE (FEC only) | Over-the-air size (FEC + IL) |
|---|---|---|---|
| 12 | 14 | 23 | 64 |
| 20 | 22 | 37 | 64 |
| 52 | 54 | 93 | 64 |

The over-the-air size when interleaving is always `INTERLEAVE_ROWS = 64` bytes, regardless of `DATA_LEN`, because each transmitted packet is one column of the `64 × FEC_PAYLOADSIZE` interleaving matrix.

---

## 7. Quick Reference — Experiment Checklist

| | Baseline | FEC only | FEC + Interleaving |
|---|---|---|---|
| `USE_FEC` | 0 | 1 | 1 |
| `USE_INTERLEAVING` | 0 | 0 | 1 |
| `DATA_LEN` | 12 / 20 / 52 | 12 / 20 / 52 | 12 / 20 / 52 |
| `PAYLOADSIZE` (notebook) | 14 / 22 / 54 | 14 / 22 / 54 | 64 |
| Analysis function | `compute_per` | `compute_per_fec` | `compute_per_fec_interleaved` |
| Latency before first TX | Immediate | Immediate | ~16 s (64 packets × 250 ms) |
