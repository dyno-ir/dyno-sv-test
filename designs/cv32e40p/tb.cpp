#include "sim_runner.h"
#include "sim_header.h"

struct Cv32e40pBus : SimRunner<ModInst____Top, Cv32e40pBus> {
  using SimRunner<ModInst____Top, Cv32e40pBus>::SimRunner;

  uint64_t fetches = 0;
  bool instrPending = false;
  bool dataPending = false;
  uint32_t instrData = 0;
  uint32_t dataData = 0;

  void init() {
    top->top->clk_i = 0;
    top->top->rst_ni = 0;
    top->top->pulp_clock_en_i = 1;
    top->top->scan_cg_en_i = 0;
    top->top->boot_addr_i = 0;
    top->top->mtvec_addr_i = 0;
    top->top->dm_halt_addr_i = 0;
    top->top->hart_id_i = 0;
    top->top->dm_exception_addr_i = 0;
    top->top->irq_i = 0;
    top->top->debug_req_i = 0;
    top->top->fetch_enable_i = 1;
    top->top->instr_gnt_i = 0;
    top->top->instr_rvalid_i = 0;
    top->top->instr_rdata_i = 0;
    top->top->data_gnt_i = 0;
    top->top->data_rvalid_i = 0;
    top->top->data_rdata_i = 0;
  }

  void step(uint64_t cycle) {
    if (cycle == 10)
      top->top->rst_ni = 1;

    if (top->top->clk_i.u32() == 0) {
      if (top->top->rst_ni.u32() == 0) {
        top->top->instr_gnt_i = 0;
        top->top->instr_rvalid_i = 0;
        top->top->instr_rdata_i = 0;
        top->top->data_gnt_i = 0;
        top->top->data_rvalid_i = 0;
        top->top->data_rdata_i = 0;
        instrPending = false;
        dataPending = false;
      } else {
        if (!instrPending && top->top->instr_req_o.u32()) {
          uint32_t addr = top->top->instr_addr_o.u32();
          instrData = read(addr);
          instrPending = true;
          top->top->instr_gnt_i = 1;
          top->top->instr_rvalid_i = 0;
          top->top->instr_rdata_i = 0;
          ++fetches;
        } else if (instrPending) {
          top->top->instr_gnt_i = 0;
          top->top->instr_rvalid_i = 1;
          top->top->instr_rdata_i = instrData;
          instrPending = false;
        } else {
          top->top->instr_gnt_i = 0;
          top->top->instr_rvalid_i = 0;
          top->top->instr_rdata_i = 0;
        }

        if (!dataPending && top->top->data_req_o.u32()) {
          uint32_t addr = top->top->data_addr_o.u32();
          if (top->top->data_we_o.u32())
            write(addr, top->top->data_wdata_o.u32(),
                  top->top->data_be_o.u32());
          dataData = read(addr);
          dataPending = true;
          top->top->data_gnt_i = 1;
          top->top->data_rvalid_i = 0;
          top->top->data_rdata_i = 0;
        } else if (dataPending) {
          top->top->data_gnt_i = 0;
          top->top->data_rvalid_i = 1;
          top->top->data_rdata_i = dataData;
          dataPending = false;
        } else {
          top->top->data_gnt_i = 0;
          top->top->data_rvalid_i = 0;
          top->top->data_rdata_i = 0;
        }
      }
    }
  }

  bool check() { return top->top->core_sleep_o.u32() != 0; }

  SimRegisterHandle &clock() { return top->top->clk_i; }
};

int main(int argc, char **argv) {
  Cv32e40pBus sim{argc, argv};
  return sim.run("CV32E40P");
}
