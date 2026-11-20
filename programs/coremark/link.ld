SECTIONS
{
  . = 0;
  .text : { *(.text*) }
  .rodata : { *(.rodata*) }
  .data : { *(.data*) }
  .bss : { *(.bss*) }
  _stack_top = 0x00020000;
}
