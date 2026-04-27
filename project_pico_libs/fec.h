#ifndef FEC_H
#define FEC_H

#include <stdint.h>

void hamming_encode(const uint8_t *data, uint8_t *encoded, uint8_t data_len);

#endif /* FEC_H */