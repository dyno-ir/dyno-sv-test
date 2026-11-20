#include "sim_runner.h"
#include "sim_header.h"

struct ServBus : SimRunner<ModInst____Top, ServBus> {
  using SimRunner<ModInst____Top, ServBus>::SimRunner;

  uint64_t fetches = 0;
  bool lastDbusCyc = false;

  void init() {
    top->top->clk = 0;
    top->top->i_rst = 1;
    top->top->i_timer_irq = 0;
    top->top->i_ibus_rdt = 0;
    top->top->i_ibus_ack = 0;
    top->top->i_dbus_rdt = 0;
    top->top->i_dbus_ack = 0;
    top->top->i_ext_rd = 0;
    top->top->i_ext_ready = 0;
  }

  void step(uint64_t cycle) {
    if (cycle == 10)
      top->top->i_rst = 0;

    if (top->top->i_rst.u32()) {
      top->top->i_ibus_rdt = 0;
      top->top->i_ibus_ack = 0;
      top->top->i_dbus_rdt = 0;
      top->top->i_dbus_ack = 0;
      lastDbusCyc = false;
    } else {
      if (top->top->o_ibus_cyc.u32()) {
        uint32_t addr = top->top->o_ibus_adr.u32();
        top->top->i_ibus_rdt = read(addr);
        top->top->i_ibus_ack = 1;
        ++fetches;
      } else {
        top->top->i_ibus_rdt = 0;
        top->top->i_ibus_ack = 0;
      }

      if (top->top->o_dbus_cyc.u32()) {
        uint32_t addr = top->top->o_dbus_adr.u32();
        uint32_t data = top->top->o_dbus_dat.u32();
        uint32_t sel = top->top->o_dbus_sel.u32();
        if (!lastDbusCyc && top->top->o_dbus_we.u32())
          write(addr, data, sel);
        top->top->i_dbus_rdt = read(addr);
        top->top->i_dbus_ack = 1;
      } else {
        top->top->i_dbus_rdt = 0;
        top->top->i_dbus_ack = 0;
      }
      lastDbusCyc = top->top->o_dbus_cyc.u32() != 0;
    }
  }

  bool check() { return false; }

  SimRegisterHandle &clock() { return top->top->clk; }
};

int main(int argc, char **argv) {
  ServBus sim{argc, argv};
  return sim.run("SERV");
}
