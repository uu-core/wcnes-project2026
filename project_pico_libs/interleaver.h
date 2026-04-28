#ifndef INTERLEAVER_H
#define INTERLEAVER_H

#include <stdint.h>
#include "packet_generation.h"

#define INTERLEAVE_ROWS 64              /* number of packets per block (depth) */
#define INTERLEAVE_COLS FEC_PAYLOADSIZE /* bytes per packet */

void interleave_block(uint8_t matrix[INTERLEAVE_ROWS][INTERLEAVE_COLS],
                      uint8_t row,
                      const uint8_t *packet);

void deinterleave_block(const uint8_t matrix[INTERLEAVE_ROWS][INTERLEAVE_COLS],
                        uint8_t row,
                        uint8_t *packet);

#endif