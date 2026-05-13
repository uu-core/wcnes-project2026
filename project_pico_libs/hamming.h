/*
  Hamming code library for backscatter project in WCNES at Uppsala University
  Authors: Albin Kjellson, Oskar Svanström, Samson Kahsay Tesfalem
*/
#ifndef HAMMING_H
#define HAMMING_H

#include <stdint.h>
#include <inttypes.h>

// Hamming(TOTAL_BITS,DATA_BITS)
#define TOTAL_BITS 127
#define DATA_BITS 120
#define BITS_IN_BYTE 8

/*
    Encode a payload using hamming code
    byte array: The original payload
    payload_length: The length of the original payload (in bits)
    total_bits: Hamming code total bits (e.g. 7 for Hamming(7,4))
    data_bits: Hamming code data bits (e.g. 4 for Hamming(7,4))
    buffer: returned data
*/
void encode(uint8_t *byte_array, uint16_t payload_length_bits, uint8_t total_bits, uint8_t data_bits, uint8_t *buffer);

#endif
