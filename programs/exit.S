#ifndef HALT_ADDR
#define HALT_ADDR 0x90000000
#endif

.globl mytest_ret
mytest_ret:
    li a0, HALT_ADDR
    sw zero, 0(a0)
    j mytest_ret
