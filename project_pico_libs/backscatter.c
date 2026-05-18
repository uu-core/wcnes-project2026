/*
 * Tobias Mages & Wenqing Yan
 * Course: Wireless Communication and Networked Embedded Systems, Project VT2023
 * Backscatter PIO
 * 29-March-2023
 *
 * Modified to support multiple antenna configurations:
 *
 *   ANTENNA_SINGLE      – 1 antenna, 1 SM
 *   ANTENNA_LAMBDA2_0   – 2 ant, λ/2,  0° phase  (original behaviour)
 *   ANTENNA_LAMBDA2_180 – 2 ant, λ/2, 180° phase (differential)
 *   ANTENNA_LAMBDA4_90  – 2 ant, λ/4,  90° phase (quadrature, 2 SMs)
 *   ANTENNA_FOUR        – 4 ant rectangle,        (2 SMs, full QPSK)
 *
 * Key changes vs original
 * ───────────────────────
 *  1. generatePIOprogram() now takes explicit opt_side_1 / opt_side_0
 *     words so the caller can choose 0° or 180° pin2 phase.
 *  2. backscatter_program_init() selects those words from antenna_cfg.
 *  3. New backscatter_program_init_multi() handles λ/4 and 4-antenna
 *     by running two independent state machines, the second one
 *     started exactly T/4 after the first.
 *  4. New backscatter_send_multi() feeds both SMs with the same data.
 */

#include "backscatter.h"

/* ═══════════════════════════════════════════════════════════════════
 *  Helper: repeat an instruction to fill a given number of cycles
 * ═══════════════════════════════════════════════════════════════════ */
int16_t repeat(uint16_t *instructionBuffer, int16_t delay,
               uint32_t asm_instr, uint8_t *length, uint16_t max_delay)
{
    while (delay > 0) {
        uint8_t delay_part = min(max_delay, delay) - 1;
        instructionBuffer[(*length)] =
            asm_instr | (((max_delay - 1) & delay_part) << 8);
        delay -= (delay_part + 1);
        (*length)++;
    }
    return 0;
}

/* ═══════════════════════════════════════════════════════════════════
 *  Helper: how many instructions are needed for this delay?
 * ═══════════════════════════════════════════════════════════════════ */
uint8_t instructionCount(uint16_t delay, uint16_t max_delay)
{
    if (delay % max_delay == 0)
        return delay / max_delay;
    else
        return delay / max_delay + 1;
}

/* ═══════════════════════════════════════════════════════════════════
 *  generatePIOprogram
 *
 *  Now accepts explicit opt_side_1 / opt_side_0 so the caller can
 *  choose 0° (both pins same) or 180° (pins opposite) phase.
 *
 *  When twoAntennas == false both opt_side words should be 0x0000.
 * ═══════════════════════════════════════════════════════════════════ */
bool generatePIOprogram(uint16_t d0, uint16_t d1, uint32_t baud,
                        uint16_t *instructionBuffer,
                        struct pio_program *backscatter_program,
                        bool twoAntennas,
                        uint16_t opt_side_1,
                        uint16_t opt_side_0)
{
    /* With twoAntennas the sideset bits steal delay bits →
       max delay per instruction drops from 32 to 8.          */
    uint16_t MAX_ASMDELAY = twoAntennas ? 0x0008 : 0x0020;

    /* Label positions */
    uint8_t get_symbol_label = 3;
    uint8_t send_1_label     = 5;
    uint8_t loop_1_label     = send_1_label + 1;

    int16_t lastPeriodCycles1 =
        (((uint32_t)CLKFREQ * 1000000) / baud - 4) % ((uint32_t)d1);
    int16_t lastPeriodCycles0 =
        (((uint32_t)CLKFREQ * 1000000) / baud - 4) % ((uint32_t)d0);

    int16_t tmp1 = min(lastPeriodCycles1, d1 / 2);
    int16_t tmp0 = min(lastPeriodCycles0, d0 / 2);

    uint8_t send_0_label =
        loop_1_label
        + instructionCount(d1 / 2,     MAX_ASMDELAY)
        + instructionCount(d1 / 2 - 1, MAX_ASMDELAY)
        + 1
        + instructionCount(tmp1,                          MAX_ASMDELAY)
        + instructionCount(max(0, lastPeriodCycles1-tmp1),MAX_ASMDELAY)
        + 1;
    uint8_t loop_0_label = send_0_label + 1;

    /* ── Check the program fits in 32-instruction memory ── */
    if (loop_0_label
        + instructionCount(d0 / 2,     MAX_ASMDELAY)
        + instructionCount(d0 / 2 - 1, MAX_ASMDELAY)
        + 1
        + instructionCount(tmp0,                          MAX_ASMDELAY)
        + instructionCount(max(0, lastPeriodCycles0-tmp0),MAX_ASMDELAY)
        + 1 >= 32)
    {
        printf("ERROR: Clock dividers are too small – program exceeds "
               "32-instruction limit. Reduce d0/d1 or disable twoAntennas "
               "(MAX_ASMDELAY rises 8→32, greatly reducing code size).\n");
        return false;
    }

    /* ── Generate state-machine instructions ── */
    instructionBuffer[0] = ASM_SET_PINS | opt_side_1 | 1;          /* set pins,1  side 1 */
    instructionBuffer[1] = ASM_OUT | (ASM_ISR_REG << 5);           /* out  isr,32        */
    instructionBuffer[2] = ASM_OUT | (ASM_Y_REG   << 5);           /* out  y,32          */
    instructionBuffer[3] = ASM_OUT | (ASM_X_REG   << 5) | 1;       /* out  x,1           */
    instructionBuffer[4] = ASM_JMP_NOTX | (0x1F & send_0_label);   /* jmp  !x, send_0    */

    /* ── Symbol 1 ── */
    instructionBuffer[5] = ASM_MOV | (ASM_X_REG << 5) | ASM_Y_REG; /* mov x, y */
    uint8_t length = 6;

    repeat(instructionBuffer, d1 / 2,     ASM_SET_PINS | opt_side_1 | 1, &length, MAX_ASMDELAY);
    repeat(instructionBuffer, d1 / 2 - 1, ASM_SET_PINS | opt_side_0 | 0, &length, MAX_ASMDELAY);
    instructionBuffer[length++] = ASM_JMP_XMM | (0x1F & loop_1_label);

    repeat(instructionBuffer, tmp1,                           ASM_SET_PINS | opt_side_1 | 1, &length, MAX_ASMDELAY);
    repeat(instructionBuffer, max(0, lastPeriodCycles1-tmp1), ASM_SET_PINS | opt_side_0 | 0, &length, MAX_ASMDELAY);
    instructionBuffer[length++] = ASM_JMP | get_symbol_label;

    /* ── Symbol 0 ── */
    instructionBuffer[length++] = ASM_MOV | (ASM_X_REG << 5) | ASM_ISR_REG; /* mov x, isr */

    repeat(instructionBuffer, d0 / 2,     ASM_SET_PINS | opt_side_1 | 1, &length, MAX_ASMDELAY);
    repeat(instructionBuffer, d0 / 2 - 1, ASM_SET_PINS | opt_side_0 | 0, &length, MAX_ASMDELAY);
    instructionBuffer[length++] = ASM_JMP_XMM | (0x1F & loop_0_label);

    repeat(instructionBuffer, tmp0,                           ASM_SET_PINS | opt_side_1 | 1, &length, MAX_ASMDELAY);
    repeat(instructionBuffer, max(0, lastPeriodCycles0-tmp0), ASM_SET_PINS | opt_side_0 | 0, &length, MAX_ASMDELAY);
    instructionBuffer[length] = ASM_JMP | get_symbol_label;

    backscatter_program->instructions = instructionBuffer;
    backscatter_program->length       = length + 1;
    backscatter_program->origin       = -1;
    return true;
}

/* ═══════════════════════════════════════════════════════════════════
 *  Internal helper – load one PIO program and start one SM.
 *
 *  pin_set     the SET pin  (drives antenna switch CTR directly)
 *  pin_side    the SIDESET pin (drives second switch, 0 = unused)
 *  use_sideset true when a second pin should be driven via sideset
 *  opt_side_1 / opt_side_0  sideset words (0 when use_sideset=false)
 * ═══════════════════════════════════════════════════════════════════ */
static bool _init_one_sm(PIO pio, uint sm, uint offset,
                          uint pin_set, uint pin_side,
                          bool use_sideset,
                          uint16_t d0, uint16_t d1, uint32_t baud,
                          uint16_t *instructionBuffer,
                          uint16_t opt_side_1, uint16_t opt_side_0,
                          struct pio_program *prog_out)
{
    /* Generate program */
    if (!generatePIOprogram(d0, d1, baud, instructionBuffer, prog_out,
                             use_sideset, opt_side_1, opt_side_0))
        return false;

    pio_add_program_at_offset(pio, prog_out, offset);

    /* GPIO setup */
    pio_gpio_init(pio, pin_set);
    pio_sm_set_consecutive_pindirs(pio, sm, pin_set, 1, true);
    if (use_sideset) {
        pio_gpio_init(pio, pin_side);
        pio_sm_set_consecutive_pindirs(pio, sm, pin_side, 1, true);
    }

    /* SM config */
    pio_sm_config c = pio_get_default_sm_config();
    sm_config_set_wrap(&c, offset, offset + prog_out->length - 1);
    sm_config_set_set_pins(&c, pin_set, 1);
    if (use_sideset) {
        sm_config_set_sideset(&c, 2, true, false);
        sm_config_set_sideset_pins(&c, pin_side);
    }
    sm_config_set_fifo_join(&c, PIO_FIFO_JOIN_TX);
    sm_config_set_out_shift(&c, false, true, 32); /* MSB first, autopull 32 */
    pio_sm_init(pio, sm, offset, &c);
    /* NOTE: caller starts the SM (pio_sm_set_enabled) */
    return true;
}

/* ═══════════════════════════════════════════════════════════════════
 *  Internal helper – compute and print RF parameters
 * ═══════════════════════════════════════════════════════════════════ */
static void _compute_config(uint16_t d0, uint16_t d1, uint32_t baud,
                             struct backscatter_config *config)
{
    uint32_t fcenter    = (CLKFREQ*1000000/d0 + CLKFREQ*1000000/d1) / 2;
    uint32_t fdeviation = (uint32_t)abs(
        (int32_t)round(((double)CLKFREQ*1000000 / (double)d1) - (double)fcenter));

    config->baudrate      = baud;
    config->center_offset = fcenter;
    config->deviation     = fdeviation;
    config->minRxBw       = baud + 2 * fdeviation;

    if (fdeviation > 380000)
        printf("WARNING: deviation too large for CC2500\n");
    if (fdeviation > 1000000)
        printf("WARNING: deviation too large for CC1352\n");
    if (d0 < d1)
        printf("WARNING: symbol 0 assigned to larger frequency than symbol 1\n");

    printf("Computed baseband settings:\n"
           "  baudrate      : %u\n"
           "  center_offset : %u\n"
           "  deviation     : %u\n"
           "  RX bandwidth  : %u\n",
           config->baudrate, config->center_offset,
           config->deviation, config->minRxBw);
}

/* ═══════════════════════════════════════════════════════════════════
 *  Internal helper – push repeat-count seed values into SM FIFO
 * ═══════════════════════════════════════════════════════════════════ */
static void _push_reps(PIO pio, uint sm,
                       uint16_t d0, uint16_t d1, uint32_t baud)
{
    uint32_t reps0 = ((CLKFREQ*1000000 / baud - 4) / d0) - 1;
    uint32_t reps1 = ((CLKFREQ*1000000 / baud - 4) / d1) - 1;
    pio_sm_put_blocking(pio, sm, reps0);
    pio_sm_put_blocking(pio, sm, reps1);
}

/* ═══════════════════════════════════════════════════════════════════
 *  backscatter_program_init
 *
 *  Handles ANTENNA_SINGLE, ANTENNA_LAMBDA2_0, ANTENNA_LAMBDA2_180
 *  with a single state machine.
 *
 *  For ANTENNA_LAMBDA4_90 / ANTENNA_FOUR use
 *  backscatter_program_init_multi() instead.
 * ═══════════════════════════════════════════════════════════════════ */
void backscatter_program_init(PIO pio, uint sm,
                              uint pin1, uint pin2,
                              uint16_t d0, uint16_t d1, uint32_t baud,
                              struct backscatter_config *config,
                              uint16_t *instructionBuffer,
                              antenna_config_t antenna_cfg)
{
    pio_sm_set_enabled(pio, sm, false);

    /* Validate */
    if (d0 % 2 != 0)
        printf("WARNING: d0 must be even – SM may not function correctly\n");
    if (d1 % 2 != 0)
        printf("WARNING: d1 must be even – SM may not function correctly\n");

    /* Correct baud rate to nearest achievable value */
    if (((uint32_t)(CLKFREQ * 1000000)) % baud != 0) {
        uint32_t baud_new = (uint32_t)round(
            (double)(CLKFREQ * 1000000) /
            round((double)(CLKFREQ * 1000000) / (double)baud));
        printf("WARNING: %u Baud not achievable at %d MHz – "
               "using %u Baud instead.\n", baud, CLKFREQ, baud_new);
        baud = baud_new;
    }

    /* Choose sideset words and whether to drive pin2 */
    bool     use_sideset = false;
    uint16_t opt_side_1  = 0x0000;
    uint16_t opt_side_0  = 0x0000;

    switch (antenna_cfg) {

        case ANTENNA_SINGLE:
            /*
             * Single antenna – pin2 is not used.
             * MAX_ASMDELAY = 32 (full range).
             */
            use_sideset = false;
            opt_side_1  = 0x0000;
            opt_side_0  = 0x0000;
            printf("[backscatter] Mode: SINGLE ANTENNA\n");
            break;

        case ANTENNA_LAMBDA2_0:
            /*
             * λ/2 spacing, 0° phase – pin2 mirrors pin1 exactly.
             * Both antennas switch simultaneously (in-phase array).
             * MAX_ASMDELAY = 8.
             */
            use_sideset = true;
            opt_side_1  = SIDESET_0DEG_HIGH;   /* pin2=1 when pin1=1 */
            opt_side_0  = SIDESET_0DEG_LOW;    /* pin2=0 when pin1=0 */
            printf("[backscatter] Mode: LAMBDA/2 0deg (in-phase)\n");
            break;

        case ANTENNA_LAMBDA2_180:
            /*
             * λ/2 spacing, 180° phase – pin2 is always opposite pin1.
             * Differential backscatter; better noise rejection vs 0°.
             * Only code change from 0° is swapping the two sideset words.
             * MAX_ASMDELAY = 8.
             */
            use_sideset = true;
            opt_side_1  = SIDESET_180DEG_HIGH; /* pin2=0 when pin1=1 */
            opt_side_0  = SIDESET_180DEG_LOW;  /* pin2=1 when pin1=0 */
            printf("[backscatter] Mode: LAMBDA/2 180deg (differential)\n");
            break;

        case ANTENNA_LAMBDA4_90:
        case ANTENNA_FOUR:
            printf("ERROR: LAMBDA4_90 and FOUR require two state machines.\n"
                   "       Use backscatter_program_init_multi() instead.\n");
            return;
    }

    /* Build and load program */
    struct pio_program prog;
    if (!_init_one_sm(pio, sm, /*offset=*/0,
                      pin1, pin2, use_sideset,
                      d0, d1, baud,
                      instructionBuffer,
                      opt_side_1, opt_side_0,
                      &prog))
        return;

    /* Start SM, push repeat-count seeds */
    pio_sm_set_enabled(pio, sm, true);
    _push_reps(pio, sm, d0, d1, baud);
    _compute_config(d0, d1, baud, config);
}

/* ═══════════════════════════════════════════════════════════════════
 *  backscatter_program_init_multi
 *
 *  Handles ANTENNA_LAMBDA4_90 and ANTENNA_FOUR using two SMs.
 *
 *  LAMBDA4_90  (2 antennas, λ/4 spacing, 90° phase):
 *  ─────────────────────────────────────────────────
 *    SM0 → pin1 (AE1, 0°  reference)
 *    SM1 → pin2 (AE2, 90° = T/4 delayed)
 *    Both SMs run the single-antenna program (twoAntennas=false)
 *    → MAX_ASMDELAY=32, full d0/d1 flexibility.
 *    SM0 starts first; SM1 starts exactly T/4 cycles later.
 *    pin3, pin4 are unused (pass 0).
 *
 *  ANTENNA_FOUR (4 antennas, λ/2 × λ/4 rectangle):
 *  ──────────────────────────────────────────────────
 *    SM0 drives AE1(pin1) + AE2(pin2) as a λ/2 180° pair.
 *    SM1 drives AE3(pin3) + AE4(pin4) as a λ/2 180° pair,
 *        started T/4 later → 90° behind SM0.
 *
 *    Resulting phase map:
 *      AE1=0°  AE2=180°
 *      AE3=90° AE4=270°   ← full QPSK quadrants
 *
 *    MAX_ASMDELAY = 8 (twoAntennas=true for each SM).
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
                                    struct backscatter_multi *ctx)
{
    pio_sm_set_enabled(pio, sm0, false);
    pio_sm_set_enabled(pio, sm1, false);

    if (d0 % 2 != 0)
        printf("WARNING: d0 must be even\n");
    if (d1 % 2 != 0)
        printf("WARNING: d1 must be even\n");

    /* Correct baud rate */
    if (((uint32_t)(CLKFREQ * 1000000)) % baud != 0) {
        uint32_t baud_new = (uint32_t)round(
            (double)(CLKFREQ * 1000000) /
            round((double)(CLKFREQ * 1000000) / (double)baud));
        printf("WARNING: %u Baud not achievable – using %u Baud.\n",
               baud, baud_new);
        baud = baud_new;
    }

    /* Quarter-period in CPU cycles (used to delay SM1 start) */
    uint32_t quarter_period_cycles =
        (uint32_t)((double)(CLKFREQ * 1000000) / (double)baud / 4.0);

    struct pio_program prog0, prog1;

    if (antenna_cfg == ANTENNA_LAMBDA4_90) {
        /*
         * Two single-antenna programs, one per SM.
         * No sideset → MAX_ASMDELAY = 32 for both.
         * SM0 offset=0, SM1 offset=prog0.length (no overlap needed
         * if using the same PIO block; each SM has its own PC).
         * For simplicity load both at offset 0 – the RP2040 allows
         * two SMs to share the same program.
         */
        printf("[backscatter] Mode: LAMBDA/4 90deg (quadrature, 2 SMs)\n");

        if (!_init_one_sm(pio, sm0, 0,
                          pin1, 0, false,
                          d0, d1, baud, instructionBuffer0,
                          0x0000, 0x0000, &prog0))
            return;

        if (!_init_one_sm(pio, sm1, 0,
                          pin2, 0, false,
                          d0, d1, baud, instructionBuffer1,
                          0x0000, 0x0000, &prog1))
            return;

    } else if (antenna_cfg == ANTENNA_FOUR) {
        /*
         * SM0: AE1(pin1) + AE2(pin2), 180° differential pair
         * SM1: AE3(pin3) + AE4(pin4), 180° differential pair
         * Both use twoAntennas=true → MAX_ASMDELAY = 8.
         * SM1 starts T/4 later → AE3=90°, AE4=270°.
         */
        printf("[backscatter] Mode: FOUR ANTENNA rectangle "
               "(0/90/180/270 deg, 2 SMs)\n");

        if (!_init_one_sm(pio, sm0, 0,
                          pin1, pin2, true,
                          d0, d1, baud, instructionBuffer0,
                          SIDESET_180DEG_HIGH, SIDESET_180DEG_LOW,
                          &prog0))
            return;

        if (!_init_one_sm(pio, sm1, 0,
                          pin3, pin4, true,
                          d0, d1, baud, instructionBuffer1,
                          SIDESET_180DEG_HIGH, SIDESET_180DEG_LOW,
                          &prog1))
            return;

    } else {
        printf("ERROR: backscatter_program_init_multi called with a "
               "single-SM antenna_cfg. Use backscatter_program_init().\n");
        return;
    }

    /* ── Push repeat-count seeds BEFORE starting SMs ── */
    /* SM0 */
    pio_sm_set_enabled(pio, sm0, true);
    _push_reps(pio, sm0, d0, d1, baud);

    /*
     * Wait exactly T/4 cycles then start SM1.
     * busy_wait_at_least_cycles() is provided by pico-sdk (pico/time.h).
     * For maximum precision disable interrupts around this section.
     */
    busy_wait_at_least_cycles(quarter_period_cycles);

    /* SM1 – now 90° (T/4) behind SM0 */
    pio_sm_set_enabled(pio, sm1, true);
    _push_reps(pio, sm1, d0, d1, baud);

    /* Fill context for backscatter_send_multi() */
    ctx->pio  = pio;
    ctx->sm0  = sm0;
    ctx->sm1  = sm1;
    ctx->mode = antenna_cfg;

    _compute_config(d0, d1, baud, config);
}

/* ═══════════════════════════════════════════════════════════════════
 *  backscatter_send  –  single SM (SINGLE / LAMBDA2_0 / LAMBDA2_180)
 * ═══════════════════════════════════════════════════════════════════ */
void backscatter_send(PIO pio, uint sm,
                      uint32_t *message, uint32_t len)
{
    for (uint32_t i = 0; i < len; i++)
        pio_sm_put_blocking(pio, sm, message[i]);
    sleep_ms(1); /* wait for transmission to finish */
}

/* ═══════════════════════════════════════════════════════════════════
 *  backscatter_send_multi  –  dual SM (LAMBDA4_90 / ANTENNA_FOUR)
 *
 *  Pushes identical data words to both SM FIFOs so both antennas
 *  transmit the same bit stream (just with a T/4 phase offset that
 *  was fixed at init time).
 * ═══════════════════════════════════════════════════════════════════ */
void backscatter_send_multi(struct backscatter_multi *ctx,
                            uint32_t *message, uint32_t len)
{
    for (uint32_t i = 0; i < len; i++) {
        pio_sm_put_blocking(ctx->pio, ctx->sm0, message[i]);
        pio_sm_put_blocking(ctx->pio, ctx->sm1, message[i]);
    }
    sleep_ms(1);
}