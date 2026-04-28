#!/Users/wenya589/.pyenv/shims/python
#
# Copyright 2023, 2023 Wenqing Yan <yanwenqingindependent@gmail.com>
#
# This file is part of the pico backscatter project
# Analyze the communication systme performance with the metrics (time, reliability and distance).

from io import StringIO
import matplotlib.pyplot as plt
import numpy as np
from functools import cache
import pandas as pd
from numpy import nan
from pylab import rcParams
rcParams["figure.figsize"] = 16, 4
import math

# read the log file
def readfile(filename):
    types = {
        "time_rx": str,
        "frame": str,
        "rssi": str,
    }
    df = pd.read_csv(
        StringIO(" ".join(l for l in open(filename))),
        skiprows=0,
        header=None,
        dtype=types,
        delimiter="|",
        on_bad_lines='warn',
        names = ["time_rx", "frame", "rssi"]
    )
    df.dropna(inplace=True)
    # covert to time data type
    df.time_rx = df.time_rx.str.rstrip().str.lstrip()
    df.time_rx = pd.to_datetime(df.time_rx, format='%H:%M:%S.%f')
    for i in range(len(df)):
        df.iloc[i,0] = df.iloc[i,0].strftime("%H:%M:%S.%f")
    # parse the payload to seq and payload
    df.frame = df.frame.str.rstrip().str.lstrip()
    df = df[df.frame.str.contains("packet overflow") == False]
    df['seq'] = df.frame.apply(lambda x: int(x[3:5], base=16))
    df['payload'] = df.frame.apply(lambda x: x[6:])
    # parse the rssi data
    df.rssi = df.rssi.str.lstrip().str.split(" ", expand=True).iloc[:,0]
    df.rssi = df.rssi.astype('int')
    df = df.drop(columns=['frame'])
    df.reset_index(inplace=True)
    return df

# parse the hex payload, return a list with int numbers for each byte
def parse_payload(payload_string):
    tmp = map(lambda x: int(x, base=16), payload_string.split())
    return list(tmp)


def popcount(n):
    return bin(n).count("1")

# compare the received frame and transmitted frame and compute the number of bit errors
def compute_bit_errors(payload, sequence, PACKET_LEN=32):
    return sum(
        map(
            popcount,
            (
                np.array(payload[:PACKET_LEN])
                ^ np.array(sequence[: len(payload[:PACKET_LEN])])
            ),
        )
    )

# a 8-bit random number generator with uniform distribution
def rnd(seed):
    A1 = 1664525
    C1 = 1013904223
    RAND_MAX1 = 0xFFFFFFFF
    seed = ((seed * A1 + C1) & RAND_MAX1)
    return seed

# a 16-bit generator returns compressible 16-bit data sample
def data(seed):
    two_pi = np.float64(2.0 * np.float64(math.pi))
    u1 = 0
    u2 = 0
    while(u1 == 0 or u2 == 0):
        seed = rnd(seed)
        u1 = np.float64(seed/0xFFFFFFFF)
        seed = rnd(seed)
        u2 = np.float64(seed/0xFFFFFFFF)
    tmp = 0x7FF * np.float64(math.sqrt(np.float64(-2.0 * np.float64(math.log(u1)))))
    return np.trunc(max([0,min([0x3FFFFF,np.float64(np.float64(tmp * np.float64(math.cos(np.float64(two_pi * u2)))) + 0x1FFF)])])), seed

# generate the transmitted file for comparison
TOTAL_NUM_16RND = 512*40 # generate a 40MB file, in case transmit too many data (larger than required 2MB)
def generate_data(NUM_16RND, TOTAL_NUM_16RND):
    LOW_BYTE = (1 << 8) - 1
    length = int(np.ceil(TOTAL_NUM_16RND/NUM_16RND))
    index = [NUM_16RND*i*2 for i in range(length)]
    df = pd.DataFrame(index=index, columns=['data'])
    initial_seed = 0xabcd # initial seed
    pseudo_seq = 0 # (16-bit)
    seed  = initial_seed
    for i in index:
        payload_data = []
        for j in range(NUM_16RND):
            if pseudo_seq > 0xffff:
                pseudo_seq = 0
                seed = initial_seed
            pseudo_seq = pseudo_seq + 2
            number, seed = data(seed)
            payload_data.append((int(number) >> 8) - 0)
            payload_data.append(int(number) & LOW_BYTE)
        df.loc[i, "data"] = payload_data
    return df

file_content = None
def payload_for_peudo_seq(pseudo_seq,PACKET_LEN):
    global file_content
    if type(file_content) == type(None): # generate data
        file_content = generate_data(int(PACKET_LEN/2), TOTAL_NUM_16RND)
    if pseudo_seq in file_content.index:
        return file_content.loc[pseudo_seq, 'data']
    else:
        return file_content.loc[0, 'data'] # TODO: pseudo sequence not within the first expected range

def compute_ber_packet(df_row, PACKET_LEN=32):
    payload = parse_payload(df_row.payload)
    pseudoseq = int(((payload[0]<<8) - 0) + payload[1])
    expected_data = payload_for_peudo_seq(pseudoseq,PACKET_LEN)
    # compute the bit errors
    return (compute_bit_errors(payload[2:], expected_data, PACKET_LEN=PACKET_LEN), 8*(2+len(payload[2:]))) # 2+ for pseudo sequence

# main function to compute the BER for each frame, return both the error statistics dataframe and in total BER for the received data
def compute_ber(df, PACKET_LEN=32):
    # seq number initialization
    print(f"The total number of packets transmitted by the tag is {df.seq[len(df)-1]+1}.")
    if len(df) > 0:
        errors,total = zip(*[compute_ber_packet(row,PACKET_LEN) for (_,row) in df.iterrows()])
        return sum(errors)/sum(total)
    else:
        print("Warning, the log-file seems empty.")
        return 0.5

def compute_per(df, PACKET_LEN=32):
    """
    Compute Packet Error Rate (PER) over received packets only.
    A packet counts as an error if it has at least one bit error.
    Lost/missing packets are not counted.
    """
    if len(df) == 0:
        print("Warning, the log-file seems empty.")
        return 1.0
    packet_results = [compute_ber_packet(row, PACKET_LEN) for (_, row) in df.iterrows()]
    packet_errors = [1 if errors > 0 else 0 for (errors, total) in packet_results]
    return sum(packet_errors) / len(packet_errors)


def byte_error_vector(df_row, PACKET_LEN=20, skip_invalid_pseudoseq=True):
    """
    Returns a vector of length PACKET_LEN.
    Each entry is 1 if that byte position was wrong, 0 if correct.
    Uses only the actual data bytes (payload excluding the first 2 pseudo-sequence bytes).
    Returns None if the packet is invalid or the pseudo-sequence is not aligned.
    """
    payload = parse_payload(df_row.payload)
    pseudoseq = (payload[0] << 8) + payload[1]

    if skip_invalid_pseudoseq and (pseudoseq % PACKET_LEN != 0):
        return None

    received_data = payload[2:]
    expected_data = payload_for_peudo_seq(pseudoseq, PACKET_LEN)

    if len(received_data) != len(expected_data):
        return None

    return np.array(
        [1 if rx != exp else 0 for rx, exp in zip(received_data, expected_data)],
        dtype=int,
    )


# ── Hamming(7,4) decoder ──────────────────────────────────────────────────────

def hamming_decode_nibble(cw):
    """
    Decode a 7-bit Hamming(7,4) codeword, correcting any single-bit error.

    Codeword bit layout (bits 6..0):  p1  p2  d1  p3  d2  d3  d4
    Syndrome: s1 = p1^d1^d2^d4,  s2 = p2^d1^d3^d4,  s3 = p3^d2^d3^d4
    Error position (1-indexed) = (s1<<2)|(s2<<1)|s3
    """
    p1 = (cw >> 6) & 1
    p2 = (cw >> 5) & 1
    d1 = (cw >> 4) & 1
    p3 = (cw >> 3) & 1
    d2 = (cw >> 2) & 1
    d3 = (cw >> 1) & 1
    d4 =  cw        & 1

    s1 = p1 ^ d1 ^ d2 ^ d4
    s2 = p2 ^ d1 ^ d3 ^ d4
    s3 = p3 ^ d2 ^ d3 ^ d4

    error_pos = (s1 << 2) | (s2 << 1) | s3  # 1-indexed; 0 means no error

    if error_pos != 0:
        cw ^= (1 << (7 - error_pos))         # flip the erroneous bit
        d1 = (cw >> 4) & 1
        d2 = (cw >> 2) & 1
        d3 = (cw >> 1) & 1
        d4 =  cw        & 1

    return (d1 << 3) | (d2 << 2) | (d3 << 1) | d4


def hamming_decode(encoded_bytes, data_len):
    """
    Decode a Hamming(7,4)-encoded byte array back to original data.

    encoded_bytes : list/array of bytes (length = data_len * 7 // 4)
    data_len      : number of original data bytes expected
    Returns       : list of decoded bytes (length = data_len)
    """
    in_bit = 0
    decoded = []

    for _ in range(data_len):
        nibbles = []
        for _ in range(2):                        # two nibbles per byte
            cw = 0
            for b in range(6, -1, -1):            # read 7 bits MSB-first
                bit = (encoded_bytes[in_bit // 8] >> (7 - in_bit % 8)) & 1
                if bit:
                    cw |= (1 << b)
                in_bit += 1
            nibbles.append(hamming_decode_nibble(cw))
        decoded.append((nibbles[0] << 4) | nibbles[1])

    return decoded


def compute_per_fec(df, DATA_LEN):
    """
    Compute PER after Hamming(7,4) FEC decoding.

    Expects payload structure: 2 bytes pseudo-seq (unencoded)
                               + DATA_LEN * 7 // 4 bytes (Hamming-encoded data)
    DATA_LEN : number of original data bytes (12, 20, or 52)
    """
    if len(df) == 0:
        print("Warning, the log-file seems empty.")
        return 1.0

    fec_len = DATA_LEN * 7 // 4
    packet_errors = []

    for _, row in df.iterrows():
        payload = parse_payload(row.payload)
        if len(payload) < 2 + fec_len:
            packet_errors.append(1)
            continue

        pseudoseq      = int((payload[0] << 8) + payload[1])
        encoded_rx     = payload[2 : 2 + fec_len]
        decoded        = hamming_decode(encoded_rx, DATA_LEN)
        expected       = payload_for_peudo_seq(pseudoseq, DATA_LEN)

        has_error = any(d != e for d, e in zip(decoded, expected))
        packet_errors.append(1 if has_error else 0)

    return sum(packet_errors) / len(packet_errors)


# plot radar chart
def radar_plot(metrics, system_ref, title):

    categories = ['Time', 'Reliability', 'Distance']
    
    # system_ref = [62.321888, 0.201875*100, 39.956474923886844]
    system = [metrics[0], metrics[1], metrics[2]]

    label_loc = np.linspace(start=0.5 * np.pi, stop=11/6 * np.pi, num=len(categories))
    plt.figure(figsize=(8, 8))
    plt.subplot(polar=True)

    # please keep the reference for your plot, we will update the reference after each SR session
    plt.plot(np.append(label_loc, (0.5 * np.pi)), system_ref+[system_ref[0]], label='Reference', color='grey')
    plt.fill(label_loc, system_ref, color='grey', alpha=0.25)

    plt.plot(np.append(label_loc, (0.5 * np.pi)), system+[system[0]], label='Our system', color='#77A136')
    plt.fill(label_loc, system, color='#77A136', alpha=0.25)

    plt.title(title, size=20)

    lines, labels = plt.thetagrids(np.degrees(label_loc), labels=categories, fontsize=18)
    plt.legend(fontsize=18, loc='upper right')
    
    plt.show()
