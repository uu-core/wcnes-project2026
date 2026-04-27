#include <stdint.h>
#include "fec.h"

static uint8_t hamming_encode_nibble(uint8_t nibble)
{
    // extracting 4 individual bits from the nibble 
    uint8_t d1 = (nibble >> 3) & 1;
    uint8_t d2 = (nibble >> 2) & 1;
    uint8_t d3 = (nibble >> 1) & 1;
    uint8_t d4 = nibble & 1;

    // computing parity bits
    uint8_t p1 = d1 ^ d2 ^ d4;
    uint8_t p2 = d1 ^ d3 ^ d4;
    uint8_t p3 = d2 ^ d3 ^ d4;

    // return: 7 bit code word
    return (p1 << 6) | (p2 << 5) | (d1 << 4) | (p3 << 3) | (d2 << 2) | (d3 << 1) | d4;
}

void hamming_encode(const uint8_t *data, uint8_t *encoded, uint8_t data_len)
{
    uint16_t out_bit = 0;

    for (uint8_t i = 0; i < (uint8_t)(data_len * 7 / 4); i++)
    {
        encoded[i] = 0;
    }

    for (uint8_t i = 0; i < data_len; i++)
    {
        uint8_t cw[2];
        cw[0] = hamming_encode_nibble((data[i] >> 4) & 0x0F);
        cw[1] = hamming_encode_nibble(data[i] & 0x0F);

        for (uint8_t c = 0; c < 2; c++)
        {
            for (int8_t b = 6; b >= 0; b--)
            {
                if ((cw[c] >> b) & 1)
                {
                    encoded[out_bit / 8] |= (uint8_t)(1 << (7 - out_bit % 8));
                }
                out_bit++;
            }
        }
    }
}