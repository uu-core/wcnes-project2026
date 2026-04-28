#include <string.h>
#include "interleaver.h"

void interleave_block(uint8_t matrix[INTERLEAVE_ROWS][INTERLEAVE_COLS],
                      uint8_t row,
                      const uint8_t *packet)
{
  memcpy(matrix[row], packet, INTERLEAVE_COLS);
}

void deinterleave_block(const uint8_t matrix[INTERLEAVE_ROWS][INTERLEAVE_COLS],
                        uint8_t row,
                        uint8_t *packet)
{
  memcpy(packet, matrix[row], INTERLEAVE_COLS);
}
