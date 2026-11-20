#include <stddef.h>

#ifndef MMIO_BASE
#define MMIO_BASE 0x10000000
#endif
#include "coremark.h"
#include "core_portme.h"

volatile ee_s32 seed1_volatile = 0x0;
volatile ee_s32 seed2_volatile = 0x0;
volatile ee_s32 seed3_volatile = 0x66;
volatile ee_s32 seed4_volatile = ITERATIONS;
volatile ee_s32 seed5_volatile = 0;

ee_u32 default_num_contexts = 1;

static CORETIMETYPE start_time_val;
static CORETIMETYPE stop_time_val;

CORETIMETYPE barebones_clock()
{
    return *(volatile ee_u32 *)(MMIO_BASE + 4);
}

void start_time(void)
{
    start_time_val = barebones_clock();
}

void stop_time(void)
{
    stop_time_val = barebones_clock();
}

CORE_TICKS get_time(void)
{
    return stop_time_val - start_time_val;
}

secs_ret time_in_secs(CORE_TICKS ticks)
{
    return ticks / 100000;
}

void portable_init(core_portable *p, int *argc, char *argv[])
{
    (void)argc;
    (void)argv;
    p->portable_id = 1;
}

void portable_fini(core_portable *p)
{
    p->portable_id = 0;
}

void uart_send_char(char c)
{
    *(volatile ee_u32 *)0x10000000 = (ee_u32)(ee_u8)c;
}
