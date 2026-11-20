#ifndef MMIO_BASE
#define MMIO_BASE 0x10000000
#endif

#ifndef HALT_ADDR
#define HALT_ADDR 0x90000000
#endif

.globl _start
_start:
    la sp, _stack_top
    li a0, 0
    li a1, 0
    call main
    li a0, MMIO_BASE
    li a1, 'O'
    sw a1, 0(a0)
    li a1, 'K'
    sw a1, 0(a0)
    li a1, '\n'
    sw a1, 0(a0)
    li a0, HALT_ADDR
    sw zero, 0(a0)
    j _start
