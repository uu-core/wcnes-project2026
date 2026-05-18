/*
 * Tobias Mages & Wenqing Yan
 * Course: Wireless Communication and Networked Embedded Systems, Project VT2023
 * Backscatter PIO
 * 29-March-2023
 *
 * Modified to support:
 *   ANTENNA_SINGLE       - single antenna
 *   ANTENNA_LAMBDA2_0    - λ/2 spacing, 0° phase   (original twoAntennas=true)
 *   ANTENNA_LAMBDA2_180  - λ/2 spacing, 180° phase (differential)
 *   ANTENNA_LAMBDA4_90   - λ/4 spacing, 90° phase  (quadrature, 2 state machines)
 *   ANTENNA_FOUR         - 4-antenna rectangle      (2 state machines)
 */

#if !PICO_NO_HARDWARE
#include "hardware/pio.h"
#endif

#include <stdio.h>
#include <math.h>
#include <string.h>
#include "pico/stdlib.h"
#include "hardware/clocks.h"

#define CLKFREQ 125

#ifndef MINMAX
#define MINMAX
#define max(x, y) (((x) > (y)) ? (x) : (y))
#define min(x, y) (((x) < (y)) ? (x) : (y))
#endif
#define abs(x) (((x) > (0)) ? (x) : (-x))

/* ── PIO instruction opcodes ── */
#define ASM_SET_PINS  0xE000
#define ASM_OUT       0x6000
#define ASM_JMP       0x0000
#define ASM_JMP_NOTX  0x0020
#define ASM_JMP_XMM   0x0040
#define ASM_MOV       0xA000
#define ASM_X_REG     0x0001
#define ASM_Y_REG     0x0002
#define ASM_ISR_REG   0x0006

/* ── Sideset option words ── */
/*   Used when twoAntennas=true (sideset drives pin2)           */
/*   0°   — pin2 follows pin1 (both same)                       */
#define SIDESET_0DEG_HIGH   0x1800   /* pin2=1 when pin1=1      */
#define SIDESET_0DEG_LOW    0x1000   /* pin2=0 when pin1=0      */
/*   180° — pin2 is opposite to pin1                            */
#define SIDESET_180DEG_HIGH 0x1000   /* pin2=0 when pin1=1      */
#define SIDESET_180DEG_LOW  0x1800   /* pin2=1 when pin1=0      */

/* ── Antenna configuration enum ── */
typedef enum {
    ANTENNA_SINGLE,         /* 1 antenna, 1 SM, pin2 unused               */
    ANTENNA_LAMBDA2_0,      /* 2 ant, λ/2 spacing, 0°   phase, 1 SM       */
    ANTENNA_LAMBDA2_180,    /* 2 ant, λ/2 spacing, 180° phase, 1 SM       */
    ANTENNA_LAMBDA4_90,     /* 2 ant, λ/4 spacing, 90° phase,  2 SMs      */
    ANTENNA_FOUR            /* 4 ant, rectangle (λ/2 × λ/4), 2 SMs        */
} antenna_config_t;

#ifndef PIO_BACKSCATTER
#define PIO_BACKSCATTER

/* Returned by backscatter_program_init / backscatter_program_init_multi */
struct backscatter_config {
    uint32_t baudrate;
    uint32_t center_offset;
    uint32_t deviation;
    uint32_t minRxBw;
};

/*
 * Context for multi-SM configurations (λ/4 and 4-antenna).
 * Pass this to backscatter_send_multi().
 */
struct backscatter_multi {
    PIO      pio;
    uint     sm0;           /* first  state machine                        */
    uint     sm1;           /* second state machine (λ/4 and FOUR only)    */
    antenna_config_t mode;
};

#endif /* PIO_BACKSCATTER */

/* ═══════════════════════════════════════════════════════════════════
 *  Low-level helpers (unchanged API)
 * ═══════════════════════════════════════════════════════════════════ */
uint8_t instructionCount(uint16_t delay, uint16_t max_delay);
int16_t repeat(uint16_t* instructionBuffer, int16_t delay,
               uint32_t asm_instr, uint8_t *length, uint16_t max_delay);

/*
 * generatePIOprogram  –  now accepts explicit sideset HIGH/LOW words
 *                        so callers can choose 0° or 180° phase.
 *
 *   opt_side_1   sideset bits to OR in when pin1=HIGH
 *   opt_side_0   sideset bits to OR in when pin1=LOW
 *   twoAntennas  true  → MAX_ASMDELAY=8,  sideset active
 *                false → MAX_ASMDELAY=32, sideset inactive
 */
bool generatePIOprogram(uint16_t d0, uint16_t d1, uint32_t baud,
                        uint16_t *instructionBuffer,
                        struct pio_program *backscatter_program,
                        bool twoAntennas,
                        uint16_t opt_side_1,
                        uint16_t opt_side_0);

/* ═══════════════════════════════════════════════════════════════════
 *  Single-SM init  (SINGLE / LAMBDA2_0 / LAMBDA2_180)
 *
 *  antenna_cfg selects which phase relationship is used:
 *    ANTENNA_SINGLE      → pin2 ignored, single antenna
 *    ANTENNA_LAMBDA2_0   → pin2 in-phase  with pin1
 *    ANTENNA_LAMBDA2_180 → pin2 anti-phase to pin1
 *
 *  For ANTENNA_LAMBDA4_90 / ANTENNA_FOUR use
 *  backscatter_program_init_multi() instead.
 * ═══════════════════════════════════════════════════════════════════ */
void backscatter_program_init(PIO pio, uint sm,
                              uint pin1, uint pin2,
                              uint16_t d0, uint16_t d1, uint32_t baud,
                              struct backscatter_config *config,
                              uint16_t *instructionBuffer,
                              antenna_config_t antenna_cfg);

/* ═══════════════════════════════════════════════════════════════════
 *  Dual-SM init  (LAMBDA4_90 / ANTENNA_FOUR)
 *
 *  Pins:
 *    LAMBDA4_90  →  pin1=AE1  pin2=AE2  (pin3,pin4 unused)
 *    ANTENNA_FOUR → pin1=AE1  pin2=AE2  (SM0, λ/2 pair, 180°)
 *                   pin3=AE3  pin4=AE4  (SM1, λ/2 pair, 180°, T/4 delayed)
 *
 *  Two separate instruction buffers are required (buf0 for SM0,
 *  buf1 for SM1) – each must be at least 32 × uint16_t.
 *
 *  The function fills *ctx so the caller can pass it to
 *  backscatter_send_multi().
 * ═══════════════════════════════════════════════════════════════════ */
void backscatter_program_init_multi(PIO pio,
                                    uint sm0, uint sm1,
                                    uint pin1, uint pin2,
                                    uint pin3, uint pin4,
                                    uint16_t d0, uint16_t d1, uint32_t baud,
                                    struct backscatter_config *config,
                                    uint16_t *instructionBuffer0,
                                    uint16_t *instructionBuffer1,
                                    antenna_config_t antenna_cfg,
                                    struct backscatter_multi *ctx);

/* ═══════════════════════════════════════════════════════════════════
 *  Send helpers
 * ═══════════════════════════════════════════════════════════════════ */

/* Single-SM send (SINGLE / LAMBDA2_0 / LAMBDA2_180) */
void backscatter_send(PIO pio, uint sm,
                      uint32_t *message, uint32_t len);

/* Dual-SM send (LAMBDA4_90 / ANTENNA_FOUR) –
   pushes identical data to both FIFOs */
void backscatter_send_multi(struct backscatter_multi *ctx,
                            uint32_t *message, uint32_t len);