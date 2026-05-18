/**
 * Tobias Mages & Wenqing Yan
 * Backscatter PIO
 * 02-March-2023
 *
 * Modified to support:
 *   ANTENNA_SINGLE       - single antenna
 *   ANTENNA_LAMBDA2_0    - λ/2 spacing, 0°   phase (original)
 *   ANTENNA_LAMBDA2_180  - λ/2 spacing, 180° phase (differential)
 *   ANTENNA_LAMBDA4_90   - λ/4 spacing, 90°  phase (quadrature, 2 SMs)
 *   ANTENNA_FOUR         - 4-antenna rectangle     (2 SMs, full QPSK)
 *
 * ── How to switch configuration ──────────────────────────────────
 *   Change ANTENNA_CONFIG to any of the five values above.
 *   Everything else (pin assignment, PIO setup, send) adapts
 *   automatically.
 * ─────────────────────────────────────────────────────────────────
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

/* ═══════════════════════════════════════════════════════════════════
 *  SPI / radio pins  (unchanged)
 * ═══════════════════════════════════════════════════════════════════ */
#define RADIO_SPI spi0
#define RADIO_MISO 16
#define RADIO_MOSI 19
#define RADIO_SCK 18

/* ═══════════════════════════════════════════════════════════════════
 *  Antenna pins
 *
 *  SINGLE / LAMBDA2_0 / LAMBDA2_180  →  PIN_TX1, PIN_TX2
 *  LAMBDA4_90                        →  PIN_TX1 (AE1), PIN_TX2 (AE2)
 *  FOUR                              →  PIN_TX1 (AE1), PIN_TX2 (AE2),
 *                                       PIN_TX3 (AE3), PIN_TX4 (AE4)
 * ═══════════════════════════════════════════════════════════════════ */
#define PIN_TX1 6  /* AE1 – always used                */
#define PIN_TX2 27 /* AE2 – used by all multi-antenna  */
#define PIN_TX3 22  /* AE3 – FOUR only                  */
#define PIN_TX4 9  /* AE4 – FOUR only                  */

/* ═══════════════════════════════════════════════════════════════════
 *  Modulation parameters
 * ═══════════════════════════════════════════════════════════════════ */
#define CLOCK_DIV0 20       /* larger  divider → lower  freq f0 */
#define CLOCK_DIV1 18       /* smaller divider → higher freq f1 */
#define DESIRED_BAUD 100000 /* target baud rate                 */

/* ═══════════════════════════════════════════════════════════════════
 *  ── SELECT ANTENNA CONFIGURATION HERE ──
 *
 *    ANTENNA_SINGLE
 *    ANTENNA_LAMBDA2_0
 *    ANTENNA_LAMBDA2_180   ← recommended default
 *    ANTENNA_LAMBDA4_90
 *    ANTENNA_FOUR
 * ═══════════════════════════════════════════════════════════════════ */
#define ANTENNA_CONFIG ANTENNA_LAMBDA2_180

/* ═══════════════════════════════════════════════════════════════════
 *  Timing / receiver
 * ═══════════════════════════════════════════════════════════════════ */
#define TX_DURATION 250 /* ms between packets               */
#define RECEIVER 2500   /* 2500 or 1352                     */
#define CARRIER_FEQ 2450000000UL

/* ═══════════════════════════════════════════════════════════════════
 *  Derived: does this config need two state machines?
 * ═══════════════════════════════════════════════════════════════════ */
#define USES_TWO_SM ((ANTENNA_CONFIG == ANTENNA_LAMBDA4_90) || \
                     (ANTENNA_CONFIG == ANTENNA_FOUR))

int main(void)
{
    /* ── SPI setup (unchanged) ────────────────────────────────── */
    stdio_init_all();
    spi_init(RADIO_SPI, 5 * 1000000);
    gpio_set_function(RADIO_SCK, GPIO_FUNC_SPI);
    gpio_set_function(RADIO_MOSI, GPIO_FUNC_SPI);
    gpio_set_function(RADIO_MISO, GPIO_FUNC_SPI);

    bi_decl(bi_3pins_with_func(RADIO_MOSI, RADIO_MISO,
                               RADIO_SCK, GPIO_FUNC_SPI));

    gpio_init(RX_CSN);
    gpio_set_dir(RX_CSN, GPIO_OUT);
    gpio_put(RX_CSN, 1);
    bi_decl(bi_1pin_with_name(RX_CSN, "SPI Receiver CS"));

    gpio_init(CARRIER_CSN);
    gpio_set_dir(CARRIER_CSN, GPIO_OUT);
    gpio_put(CARRIER_CSN, 1);
    bi_decl(bi_1pin_with_name(CARRIER_CSN, "SPI Carrier CS"));

    sleep_ms(5000);

    /* ── Backscatter PIO setup ────────────────────────────────── */
    PIO pio = pio0;
    uint sm0 = 0;
    uint sm1 = 1; /* only used by LAMBDA4_90 / FOUR              */

    struct backscatter_config backscatter_conf;
    struct backscatter_multi multi_ctx; /* LAMBDA4_90/FOUR */

    /* Two instruction buffers – each SM needs its own 32-word buf  */
    uint16_t instructionBuffer0[32] = {0};
    uint16_t instructionBuffer1[32] = {0};

    printf("[main] Antenna config: ");
    switch (ANTENNA_CONFIG)
    {
    case ANTENNA_SINGLE:
        printf("SINGLE\n");
        break;
    case ANTENNA_LAMBDA2_0:
        printf("LAMBDA/2 0deg\n");
        break;
    case ANTENNA_LAMBDA2_180:
        printf("LAMBDA/2 180deg\n");
        break;
    case ANTENNA_LAMBDA4_90:
        printf("LAMBDA/4 90deg\n");
        break;
    case ANTENNA_FOUR:
        printf("FOUR ANTENNA\n");
        break;
    }

#if USES_TWO_SM
    /* ── Dual-SM init (LAMBDA4_90 / FOUR) ─────────────────────── */
    backscatter_program_init_multi(
        pio,
        sm0, sm1,
        PIN_TX1, PIN_TX2, /* SM0: AE1 (set), AE2 (sideset/unused) */
        PIN_TX3, PIN_TX4, /* SM1: AE3 (set), AE4 (sideset/unused) */
        CLOCK_DIV0, CLOCK_DIV1, DESIRED_BAUD,
        &backscatter_conf,
        instructionBuffer0,
        instructionBuffer1,
        ANTENNA_CONFIG,
        &multi_ctx);
#else
    /* ── Single-SM init (SINGLE / LAMBDA2_0 / LAMBDA2_180) ────── */
    backscatter_program_init(
        pio, sm0,
        PIN_TX1, PIN_TX2,
        CLOCK_DIV0, CLOCK_DIV1, DESIRED_BAUD,
        &backscatter_conf,
        instructionBuffer0,
        ANTENNA_CONFIG);
#endif

    /* ── Packet buffers (unchanged) ──────────────────────────── */
    static uint8_t message[buffer_size(PAYLOADSIZE + 2, HEADER_LEN) * 4] = {0};
    static uint32_t buffer[buffer_size(PAYLOADSIZE, HEADER_LEN)] = {0};
    static uint8_t seq = 0;
    uint8_t *header_tmplate = packet_hdr_template(RECEIVER);
    uint8_t tx_payload_buffer[PAYLOADSIZE];

    /* ── Carrier setup (unchanged) ───────────────────────────── */
    printf("\nConfiguring one CC2500 as carrier generator:\n");
    setupCarrier();
    set_frecuency_tx(CARRIER_FEQ);
    sleep_ms(1);

    /* ── Receiver setup ──────────────────────────────────────── */
    printf("\nConfiguring one CC2500 to approximate the obtained radio settings:\n");
    event_t evt = no_evt;
    Packet_status status;
    uint8_t rx_buffer[RX_BUFFER_SIZE];
    uint64_t time_us;

    setupReceiver();
    set_frecuency_rx(CARRIER_FEQ + backscatter_conf.center_offset);
    set_frequency_deviation_rx(backscatter_conf.deviation);
    set_datarate_rx(backscatter_conf.baudrate);
    set_filter_bandwidth_rx(backscatter_conf.minRxBw);
    sleep_ms(1);
    RX_start_listen();
    printf("started listening\n");
    bool rx_ready = true;

    /* ── Main loop ───────────────────────────────────────────── */
    while (true)
    {

        evt = get_event();

        switch (evt)
        {

        case rx_assert_evt:
            /* started receiving */
            rx_ready = false;
            break;

        case rx_deassert_evt:
            /* finished receiving */
            time_us = to_us_since_boot(get_absolute_time());
            status = readPacket(rx_buffer);
            printPacket(rx_buffer, status, time_us);
            RX_start_listen();
            rx_ready = true;
            break;

        case no_evt:
            if (rx_ready)
            {

                /* generate new data */
                generate_data(tx_payload_buffer, PAYLOADSIZE, true);

                /* build packet */
                add_header(&message[0], seq, header_tmplate);
                memcpy(&message[HEADER_LEN], tx_payload_buffer, PAYLOADSIZE);

                /* cast bytes → 32-bit FIFO words (MSB first) */
                for (uint8_t i = 0;
                     i < buffer_size(PAYLOADSIZE, HEADER_LEN); i++)
                {
                    buffer[i] =
                        ((uint32_t)message[4 * i]) << 24 |
                        ((uint32_t)message[4 * i + 1]) << 16 |
                        ((uint32_t)message[4 * i + 2]) << 8 |
                        ((uint32_t)message[4 * i + 3]);
                }

                /* transmit */
                startCarrier();
                sleep_ms(1); /* wait for carrier to stabilise */

#if USES_TWO_SM
                backscatter_send_multi(
                    &multi_ctx,
                    buffer,
                    buffer_size(PAYLOADSIZE, HEADER_LEN));
#else
                backscatter_send(
                    pio, sm0,
                    buffer,
                    buffer_size(PAYLOADSIZE, HEADER_LEN));
#endif
                /* wait for transmission to finish (+3 ms margin) */
                sleep_ms((uint32_t)ceil(
                             ((double)buffer_size(PAYLOADSIZE, HEADER_LEN) * 8000.0) / (double)DESIRED_BAUD) +
                         3);

                stopCarrier();
                seq++;
            }
            sleep_ms(TX_DURATION);
            break;
        }

        sleep_ms(1);
    }

    /* never reached */
    RX_stop_listen();
    stopCarrier();
}