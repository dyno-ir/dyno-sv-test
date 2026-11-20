#include <stdarg.h>
#include <stdbool.h>
#include <stddef.h>
#include "coremark.h"

static void uart_send_char(char c)
{
    *(volatile unsigned int *)0x10000000 = (unsigned char)c;
}

static void print_string(const char *s)
{
    while (*s)
        uart_send_char(*s++);
}

static void print_unsigned(unsigned long value, int base, int width, char pad)
{
    char buffer[32];
    int length = 0;
    if (value == 0)
        buffer[length++] = '0';
    else
    {
        while (value != 0)
        {
            unsigned long digit = value % base;
            buffer[length++] = (char)(digit < 10 ? '0' + digit : 'a' + digit - 10);
            value /= base;
        }
    }
    for (int i = length; i < width; ++i)
        uart_send_char(pad);
    for (int i = length - 1; i >= 0; --i)
        uart_send_char(buffer[i]);
}

static void print_signed(long value, int width, char pad)
{
    if (value < 0)
    {
        uart_send_char('-');
        value = -value;
    }
    print_unsigned((unsigned long)value, 10, width, pad);
}

int ee_printf(const char *fmt, ...)
{
    va_list args;
    va_start(args, fmt);
    for (const char *p = fmt; *p; ++p)
    {
        if (*p != '%')
        {
            uart_send_char(*p);
            continue;
        }
        ++p;
        int width = 0;
        char pad = ' ';
        if (*p == '0')
        {
            pad = '0';
            ++p;
        }
        while (*p >= '0' && *p <= '9')
        {
            width = width * 10 + (*p - '0');
            ++p;
        }
        bool is_long = false;
        if (*p == 'l')
        {
            is_long = true;
            ++p;
        }
        switch (*p)
        {
        case 's':
            print_string(va_arg(args, const char *));
            break;
        case 'd':
            print_signed(is_long ? va_arg(args, long) : va_arg(args, int), width, pad);
            break;
        case 'u':
            print_unsigned(is_long ? va_arg(args, unsigned long) : va_arg(args, unsigned int), 10, width, pad);
            break;
        case 'x':
            print_unsigned(is_long ? va_arg(args, unsigned long) : va_arg(args, unsigned int), 16, width, pad);
            break;
        case 'c':
            uart_send_char((char)va_arg(args, int));
            break;
        default:
            uart_send_char(*p);
            break;
        }
    }
    va_end(args);
    return 0;
}
