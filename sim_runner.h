#pragma once

#include "aig/AIGContext.h"
#include "dyno/Context.h"
#include "dyno/FatContext.h"
#include "hw/HWContext.h"
#include "hw/HWTypeIDs.h"
#include "hw/SimTop.h"
#include "hw/passes/ParseDyno.h"
#include "hw/passes/SelectModules.h"
#include "meta/MetaContext.h"
#include "op/OpContext.h"
#include "support/CmdLineArgs.h"
#include "support/MMap.h"
#include "support/SmallVec.h"
#include "support/StringRef.h"
#include "type/TypeContext.h"

#include <algorithm>
#include <cstdint>
#include <memory>
#include <print>

struct SimArgs {
  StringRef dyno;
  uint64_t cycles = 2000;
  StringRef top = "Top";
  StringRef program;
  uint32_t mmio = 0;
  uint32_t halt = 0;
};

class SimMemory {
  Vec<uint32_t> words;

public:
  void load(StringRef path) {
    MMap file{path};
    if (!file)
      report_fatal_error("could not open program: {}", path);
    size_t bytes = file.size() - 1;
    words.resize(std::max((bytes + 3) / 4, size_t(0x8000)), 0);
    for (size_t i = 0; i < bytes; ++i)
      words[i / 4] |= static_cast<uint32_t>(static_cast<uint8_t>(file.data()[i]))
                      << (8 * (i % 4));
  }

  uint32_t read(uint32_t addr) const {
    size_t index = addr >> 2;
    return index < words.size() ? words[index] : 0;
  }

  void write(uint32_t addr, uint32_t data, uint32_t sel) {
    size_t index = addr >> 2;
    if (index >= words.size())
      return;
    auto &word = words[index];
    for (int i = 0; i < 4; ++i)
      if (sel & (1u << i))
        reinterpret_cast<uint8_t *>(&word)[i] =
            static_cast<uint8_t>((data >> (8 * i)) & 0xff);
  }
};

template <typename Top, typename Derived> class SimRunner {
  dyno::FatContext ctx;
  SimMemory memory;
  Vec<char> output;
  uint32_t clock = 0;
  bool halted = false;

  Derived &bus() { return *static_cast<Derived *>(this); }

public:
  SimArgs args;
  std::unique_ptr<SimulationTop<Top>> top;

  SimRunner(int argc, char **argv) {
    CmdLineArg<StringRef> dynoArg{std::nullopt, "dyno", "Dyno file.",
                                  CmdLineArgFlags::POSITIONAL |
                                      CmdLineArgFlags::MANDATORY};
    CmdLineArg<uint64_t> cyclesArg{std::nullopt, "cycles", "Cycle limit.",
                                   CmdLineArgFlags::POSITIONAL, 2000};
    CmdLineArg<StringRef> topArg{std::nullopt, "top", "Top module regex.",
                                 CmdLineArgFlags::POSITIONAL, StringRef{"Top"}};
    CmdLineArg<StringRef> programArg{std::nullopt, "program", "Program binary.",
                                     CmdLineArgFlags::POSITIONAL |
                                         CmdLineArgFlags::MANDATORY};
    CmdLineArg<uint32_t> mmioArg{std::nullopt, "mmio", "MMIO base.",
                                 CmdLineArgFlags::POSITIONAL |
                                     CmdLineArgFlags::MANDATORY};
    CmdLineArg<uint32_t> haltArg{std::nullopt, "halt", "Halt address.",
                                 CmdLineArgFlags::POSITIONAL |
                                     CmdLineArgFlags::MANDATORY};

    CmdLineArgHandler handler;
    handler.registerArg(dynoArg);
    handler.registerArg(cyclesArg);
    handler.registerArg(topArg);
    handler.registerArg(programArg);
    handler.registerArg(mmioArg);
    handler.registerArg(haltArg);
    handler.parse(argc, argv);

    args.dyno = *dynoArg;
    args.cycles = *cyclesArg;
    args.top = *topArg;
    args.program = *programArg;
    args.mmio = *mmioArg;
    args.halt = *haltArg;

    ctx.add<dyno::CoreDialectContext>();
    ctx.add<dyno::MetaDialectContext>();
    ctx.add<dyno::OpDialectContext>();
    ctx.add<dyno::HWDialectContext>();
    ctx.add<dyno::AIGDialectContext>();
    ctx.add<dyno::TypeDialectContext>();
    ctx.getCtx<dyno::TypeDialectContext>().baseTypeNames.registerDialect(
        dyno::DIALECT_HW, dyno::hw::hwTypeDialectTypeNames);

    dyno::ParseDynoPass parse{ctx};
    parse.config.path = args.dyno;
    parse.run();

    dyno::SelectModulesPass select{ctx};
    select.config.regex = args.top;
    select.run();

    top = std::make_unique<SimulationTop<Top>>(ctx);
    memory.load(args.program);
  }

  uint32_t read(uint32_t addr) const {
    if (addr == args.mmio + 4)
      return clock;
    if (addr >= args.mmio && addr < args.mmio + 0x100)
      return 0;
    return memory.read(addr);
  }

  void write(uint32_t addr, uint32_t data, uint32_t sel) {
    if (addr == args.halt) {
      halted = true;
      return;
    }
    if (addr >= args.mmio && addr < args.mmio + 0x100) {
      if (sel & 1)
        output.push_back(static_cast<char>(data & 0xff));
      return;
    }
    memory.write(addr, data, sel);
  }

  void set_clock(uint32_t value) { clock = value; }
  bool is_halted() const { return halted; }
  StringRef get_output() const { return StringRef{output.data(), output.size()}; }
  bool has_result() const {
    StringRef out = get_output();
    return out.find("OK\n") != out.end();
  }
  bool has_error() const {
    StringRef out = get_output();
    return out.find("ERROR\n") != out.end();
  }
  void print_result(StringRef name, uint64_t cycles, uint64_t fetches,
                    bool failed, bool partial) const {
    std::print("{} cycles={} fetches={} failed={} partial={}\n", name, cycles,
               fetches, failed, partial);
    std::print("OUTPUT: {}\n", get_output());
  }

  int run(StringRef name) {
    bus().init();
    uint64_t cycles = 0;
    bool busFailed = false;
    for (; cycles < args.cycles; ++cycles) {
      set_clock(cycles);
      bus().step(cycles);
      auto &clk = bus().clock();
      clk = clk.u32() ^ 1;
      top->eval();
      top->forwardTime(1);
      if (is_halted())
        break;
      busFailed = bus().check();
      if (busFailed)
        break;
    }
    bool halted = is_halted();
    bool hasResult = has_result();
    bool partial = !halted && !hasResult;
    bool failed = busFailed || has_error() || (halted && !hasResult) || (!halted && hasResult);
    print_result(name, cycles, bus().fetches, failed, partial);
    return failed ? 1 : 0;
  }
};
