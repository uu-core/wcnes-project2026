/**
 * Tobias Mages & Wenqing Yan
 * Backscatter PIO
 * 02-March-2023
 *
 * See the sub-projects ... for further information:
 *  - baseband
 *  - carrier-CC2500
 *  - receiver-CC2500
 *
 */

#include <stdio.h>
#include <math.h>
#include <string.h>
#include "pico/stdlib.h"

#include "pico/util/queue.h"
#include "pico/binary_info.h"
#include "pico/util/datetime.h"
#include "hardware/spi.h"

#include "hardware/pio.h"
#include "hardware/clocks.h"
#include "backscatter.h"
#include "carrier_CC2500.h"
#include "receiver_CC2500.h"
#include "packet_generation.h"


#define RADIO_SPI             spi0
#define RADIO_MISO              16
#define RADIO_MOSI              19
#define RADIO_SCK               18

#define TX_DURATION            250 // send a packet every 250ms (when changing baud-rate, ensure that the TX delay is larger than the transmission time)
#define RECEIVER              1352 // define the receiver board either 2500 or 1352
#define PIN_TX1                  6
#define PIN_TX2                 27
#define CLOCK_DIV0              20 // larger
#define CLOCK_DIV1              18 // smaller
#define DESIRED_BAUD        100000
#define TWOANTENNAS          true

#define CARRIER_FEQ     2450000000

// --- ABR Helper Functions for CC2500 ---

// Function to send a command strobe to the CC2500
void strobe_cc2500(uint8_t cmd) {
    uint8_t tx_buf[1] = { cmd };
    gpio_put(RX_CSN, 0); // Select the receiver clicker
    spi_write_blocking(RADIO_SPI, tx_buf, 1);
    gpio_put(RX_CSN, 1); // Deselect
}

// Function to read a status register from the CC2500
uint8_t read_cc2500_status(uint8_t reg) {
    // To read a status register on the CC2500, we must add the READ burst bit (0xC0)
    uint8_t tx_buf[2] = { reg | 0xC0, 0x00 }; 
    uint8_t rx_buf[2] = { 0, 0 };
    
    gpio_put(RX_CSN, 0);
    spi_write_read_blocking(RADIO_SPI, tx_buf, rx_buf, 2);
    gpio_put(RX_CSN, 1);
    
    return rx_buf[1];
}

int main() {
    /* setup SPI and USB Serial */
    stdio_init_all();
    
    // FORCE the Pico to wait here until you open PuTTY
    while (!stdio_usb_connected()) {
        sleep_ms(100);
    }
    
    // Print a massive heartbeat so we know USB is working
    printf("\n\n=======================================\n");
    printf("--- PICO ABR TAG BOOTING UP SUCCESS ---\n");
    printf("=======================================\n\n");


    spi_init(RADIO_SPI, 5 * 1000000); // SPI0 at 5MHz.
    gpio_set_function(RADIO_SCK, GPIO_FUNC_SPI);
    gpio_set_function(RADIO_MOSI, GPIO_FUNC_SPI);
    gpio_set_function(RADIO_MISO, GPIO_FUNC_SPI);

    // Make the SPI pins available to picotool
    bi_decl(bi_3pins_with_func(RADIO_MOSI, RADIO_MISO, RADIO_SCK, GPIO_FUNC_SPI));

    // Chip select is active-low, so we'll initialise it to a driven-high state
    gpio_init(RX_CSN);
    gpio_set_dir(RX_CSN, GPIO_OUT);
    gpio_put(RX_CSN, 1);
    bi_decl(bi_1pin_with_name(RX_CSN, "SPI Receiver CS"));

    // Chip select is active-low, so we'll initialise it to a driven-high state
    gpio_init(CARRIER_CSN);
    gpio_set_dir(CARRIER_CSN, GPIO_OUT);
    gpio_put(CARRIER_CSN, 1);
    bi_decl(bi_1pin_with_name(CARRIER_CSN, "SPI Carrier CS"));

    sleep_ms(5000);

    /* setup backscatter state machine */
    PIO pio = pio0;
    uint sm = 0;
    struct backscatter_config backscatter_conf;
    uint16_t instructionBuffer[32] = {0}; // maximal instruction size: 32
    backscatter_program_init(pio, sm, PIN_TX1, PIN_TX2, CLOCK_DIV0, CLOCK_DIV1, DESIRED_BAUD, &backscatter_conf, instructionBuffer, TWOANTENNAS);

    static uint8_t message[buffer_size(PAYLOADSIZE+2, HEADER_LEN)*4] = {0};  // include 10 header bytes
    static uint32_t buffer[buffer_size(PAYLOADSIZE, HEADER_LEN)] = {0}; // initialize the buffer
    static uint8_t seq = 0;
    uint8_t *header_tmplate = packet_hdr_template(RECEIVER);
    uint8_t tx_payload_buffer[PAYLOADSIZE];



    /* Setup carrier */
    printf("\nConfiguring one CC2500 as carrier generator (DISABLED for external nRF52840):\n");
    /* Start Receiver (Used exclusively for ABR RSSI sensing) */
    printf("\nConfiguring CC2500 Clicker for RSSI sensing...\n");
    setupReceiver(); // This initializes the basic radio registers
    
    // Command 0x34 is the SRX (Strobe RX) command to put CC2500 in receive mode
    strobe_cc2500(0x34); 
    sleep_ms(10); // Give it a moment to settle



    /* Start Receiver */
    printf("\nConfiguring one CC2500 to approximate the obtained radio settings (DISABLED for external CC1352):\n");
    event_t evt = no_evt;
    Packet_status status;
    uint8_t rx_buffer[RX_BUFFER_SIZE];
    uint64_t time_us;
    
    // setupReceiver();
    // set_frecuency_rx(CARRIER_FEQ + backscatter_conf.center_offset);
    // set_frequency_deviation_rx(backscatter_conf.deviation);
    // set_datarate_rx(backscatter_conf.baudrate);
    // set_filter_bandwidth_rx(backscatter_conf.minRxBw);
    // sleep_ms(1);
    // RX_start_listen();
    
    printf("Tag is ready to backscatter!\n");
    bool rx_ready = true;
    
    // Hardware state trackers
    uint32_t active_baud = DESIRED_BAUD; 
    uint8_t weak_burst_count = 0;   // NEW: Tracks consecutive weak signals
    uint8_t strong_burst_count = 0; // NEW: Tracks consecutive strong signals
    
    /* loop */
    while (true) {
        
        // --- ABR: READ RSSI AND ADJUST RATE ---
        
        // 0. RESET RADIO STATE
        strobe_cc2500(0x36); // SIDLE
        strobe_cc2500(0x3A); // SFRX
        strobe_cc2500(0x34); // SRX
        sleep_ms(5);         // Let AGC settle
        
        // 1. Take 20 samples to calculate an AVERAGE (Noise Rejection Filter)
        int32_t total_rssi = 0;
        
        for (int i = 0; i < 20; i++) {
            uint8_t rssi_dec = read_cc2500_status(0x34);
            int16_t current_rssi_dbm; 
            uint8_t rssi_offset = 72;
            
            if (rssi_dec >= 128) {
                current_rssi_dbm = ((int16_t)rssi_dec - 256) / 2 - rssi_offset;
            } else {
                current_rssi_dbm = (rssi_dec) / 2 - rssi_offset;
            }
            
            // Add every sample together
            total_rssi += current_rssi_dbm;
            sleep_ms(1);
        }
        
        // Divide by 20 to get the smooth average
        int16_t avg_rssi_dbm = total_rssi / 20;
        
        printf("Avg RSSI: %d dBm | ", avg_rssi_dbm);

        // 3. ABR Decision Logic (Hysteresis + Debounce)
        uint32_t current_baud = active_baud; // Default to staying at the current speed

        if (active_baud == DESIRED_BAUD) { 
            // WE ARE CURRENTLY FAST (100k)
            if (avg_rssi_dbm < -75) { 
                weak_burst_count++; // Signal is weak, start counting
                strong_burst_count = 0;
                
                if (weak_burst_count >= 3) { // 3 strikes and we shift down
                    current_baud = 50000;
                    weak_burst_count = 0;
                    printf("Rate: SLOW (50k) [SHIFT TRIGGERED]\n");
                } else {
                    printf("Rate: FAST (100k) [Warning: Weak signal %d/3]\n", weak_burst_count);
                }
            } else {
                weak_burst_count = 0; // Signal recovered, reset the counter!
                printf("Rate: FAST (100k) [Stable]\n");
            }
            
        } else { 
            // WE ARE CURRENTLY SLOW (50k)
            if (avg_rssi_dbm > -60) { // Notice the -60 threshold! It must be MUCH stronger to shift up.
                strong_burst_count++; // Signal is strong, start counting
                weak_burst_count = 0;
                
                if (strong_burst_count >= 3) { // 3 strikes and we shift up
                    current_baud = DESIRED_BAUD;
                    strong_burst_count = 0;
                    printf("Rate: FAST (100k) [SHIFT TRIGGERED]\n");
                } else {
                    printf("Rate: SLOW (50k) [Notice: Strong signal %d/3]\n", strong_burst_count);
                }
            } else {
                strong_burst_count = 0; // Signal dropped again, reset the counter!
                printf("Rate: SLOW (50k) [Stable]\n");
            }
        }

        // --- NEW: THE HARDWARE GEAR SHIFTER ---
        if (current_baud != active_baud) {
            printf("\n[!] SHIFTING PIO HARDWARE TO %d BAUD [!]\n", current_baud);
            
            // 1. Turn off the state machine momentarily
            pio_sm_set_enabled(pio, sm, false);
            
            // 2. Clear the old PIO program from memory to prevent overflows
            pio_clear_instruction_memory(pio);
            
            // 3. Re-calculate and load the new bit-timings (This preserves your 6.59 MHz subcarrier!)
            backscatter_program_init(pio, sm, PIN_TX1, PIN_TX2, CLOCK_DIV0, CLOCK_DIV1, current_baud, &backscatter_conf, instructionBuffer, TWOANTENNAS);
            
            // 4. Update the tracker so it doesn't re-initialize again until the speed changes
            active_baud = current_baud;
            sleep_ms(10); // Give the silicon a tiny moment to settle
        }
        // --------------------------------------

        // 4. PREVENT RF JAMMING & PRESERVE PIO CLOCK
        strobe_cc2500(0x36); // SIDLE // SIDLE: Put the CC2500 to sleep so it doesn't jam the backscatter!
        
        // --- END ABR LOGIC ---

        /* generate new data */
        generate_data(tx_payload_buffer, PAYLOADSIZE, true);

        /* add header (10 byte) to packet */
        add_header(&message[0], seq, header_tmplate);
        /* add payload to packet */
        memcpy(&message[HEADER_LEN], tx_payload_buffer, PAYLOADSIZE);

        /* casting for 32-bit fifo */
        for (uint8_t i=0; i < buffer_size(PAYLOADSIZE, HEADER_LEN); i++) {
            buffer[i] = ((uint32_t) message[4*i+3]) | (((uint32_t) message[4*i+2]) << 8) | (((uint32_t) message[4*i+1]) << 16) | (((uint32_t)message[4*i]) << 24);
        }
        
        /* put the data to FIFO (start backscattering) */
        sleep_ms(1); 
        
        // THIS is the actual command that shifts the RF signal!
        backscatter_send(pio,sm,buffer,buffer_size(PAYLOADSIZE, HEADER_LEN));
        
        sleep_ms(ceil((((double) buffer_size(PAYLOADSIZE, HEADER_LEN))*8000.0)/((double) current_baud))+3);
        
        /* increase seq number*/ 
        seq++;
        
        // Wait before looping and sending the next packet
        sleep_ms(TX_DURATION);
    }
    /* stop carrier and receiver - never reached */
    // RX_stop_listen();
    // stopCarrier();
}
