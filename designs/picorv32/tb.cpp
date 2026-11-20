#include "sim_runner.h"
#include "sim_header.h"

struct Picorv32Bus : SimRunner<ModInst____Top, Picorv32Bus> {
  using SimRunner<ModInst____Top, Picorv32Bus>::SimRunner;

  uint64_t fetches = 0;
  bool lastValid = false;

  void init() {
    top->top->clk = 0;
    top->top->resetn = 0;
    top->top->mem_ready = 0;
    top->top->mem_rdata = 0;
    top->top->pcpi_wr = 0;
    top->top->pcpi_rd = 0;
    top->top->pcpi_wait = 0;
    top->top->pcpi_ready = 0;
    top->top->irq = 0;
  }

  void step(uint64_t cycle) {
    if (cycle == 10)
      top->top->resetn = 1;

    if (top->top->resetn.u32() == 0) {
      top->top->mem_ready = 0;
      top->top->mem_rdata = 0;
      lastValid = false;
    } else {
      uint32_t valid = top->top->mem_valid.u32();
      if (valid) {
        uint32_t addr = top->top->mem_addr.u32();
        uint32_t data = top->top->mem_wdata.u32();
        uint32_t strb = top->top->mem_wstrb.u32();
        if (!lastValid) {
          if (top->top->mem_instr.u32())
            ++fetches;
          if (!top->top->mem_instr.u32() && strb != 0)
            write(addr, data, strb);
        }
        top->top->mem_rdata = read(addr);
        top->top->mem_ready = 1;
      } else {
        top->top->mem_ready = 0;
        top->top->mem_rdata = 0;
      }
      lastValid = valid != 0;
    }
  }

  bool check() { return top->top->trap.u32() != 0; }

  SimRegisterHandle &clock() { return top->top->clk; }
};

int main(int argc, char **argv) {
  Picorv32Bus sim{argc, argv};
  return sim.run("PICORV32");
}
