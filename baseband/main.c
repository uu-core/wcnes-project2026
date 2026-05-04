/**
 * Tobias Mages & Wenqing Yan
 * Backscatter PIO
 * 02-March-2023
 */

#include <stdio.h>
#include "math.h"
#include "pico/stdlib.h"
#include "hardware/pio.h"
#include "hardware/clocks.h"
#include "backscatter.pio.h"
#include "packet_generation.h"
#include <hamming.h>

#define TX_DURATION 250 // send a packet every 250ms (when changing baud-rate, ensure that the TX delay is larger than the transmission time)
#define RECEIVER 1352 // define the receiver board either 2500 or 1352
#define PIN_TX1 6
#define PIN_TX2 27

#define BITS_IN_BYTE 8

int main() {
    PIO pio = pio0;
    uint sm = 0;
    uint offset = pio_add_program(pio, &backscatter_program);
    backscatter_program_init(pio, sm, offset, PIN_TX1, PIN_TX2); // two antenna setup
    //backscatter_program_init(pio, sm, offset, PIN_TX1); // one antenna setup

    // Calculate number of bits and bytes in the encoded payload
    static uint8_t encoded_bits = PAYLOADSIZE * BITS_IN_BYTE 
                                + ceil((double)PAYLOADSIZE * BITS_IN_BYTE/DATA_BITS) * (TOTAL_BITS - DATA_BITS) 
                                + PAYLOADSIZE * BITS_IN_BYTE / DATA_BITS;
    static uint8_t encoded_bytes = (encoded_bits + BITS_IN_BYTE - 1) / BITS_IN_BYTE; // Make int division ceil to nearest byte

    static uint8_t message[buffer_size(encoded_bytes+2, HEADER_LEN)*4] = {0};  // include 10 header bytes
    static uint32_t buffer[buffer_size(encoded_bytes+2, HEADER_LEN)] = {0}; // initialize the buffer
    static uint8_t seq = 0;
    uint8_t *header_tmplate = packet_hdr_template(RECEIVER);
    uint8_t tx_payload_buffer[PAYLOADSIZE];

    while (true) {
        /* generate new data */
        generate_data(tx_payload_buffer, PAYLOADSIZE, true);
        
        // Encode payload with hamming, method creates array with BITS in each array index
        uint8_t encoded_payload_bits[encoded_bits] = {0};
        encode(tx_payload_buffer, PAYLOADSIZE * BITS_IN_BYTE, TOTAL_BITS, DATA_BITS, encoded_payload);
        
        // Bits array to byte array for payload
        uint8_t encoded_payload[encoded_bytes] = {0};
        pack_bits_to_bytes(encoded_payload_bits, encoded_bits, encoded_payload);

        /* add header (10 byte) to packet */
        add_header(&message[0], seq, encoded_payload, header_tmplate);
        /* add payload to packet */
        memcpy(&message[HEADER_LEN], encoded_payload, encoded_bytes);

        /* casting for 32-bit fifo */
        for (uint8_t i=0; i < buffer_size(encoded_bytes+2, HEADER_LEN); i++) {
            buffer[i] = ((uint32_t) message[4*i+3]) | (((uint32_t) message[4*i+2]) << 8) | (((uint32_t) message[4*i+1]) << 16) | (((uint32_t)message[4*i]) << 24);
        }
        /* put the data to FIFO */
        backscatter_send(pio,sm,buffer,buffer_size(encoded_bytes+2, HEADER_LEN));
        seq++;
        sleep_ms(TX_DURATION);
    }
}
