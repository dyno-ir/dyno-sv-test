import os
import re
import shlex
import subprocess
import time
from collections import Counter
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
PROGRAMS_DIR = TEST_DIR / "programs"
DYNO_ROOT = Path(os.environ.get("DYNO_ROOT", TEST_DIR.parent.parent))
DYNO_BUILD = Path(os.environ.get("DYNO_BUILD", DYNO_ROOT / "build"))
DYNO_WORK = Path(os.environ.get("DYNO_WORK", DYNO_ROOT / "work"))
DYNO_SV = DYNO_BUILD / "tools" / "dyno-sv" / "dyno-sv"
FLOW = DYNO_ROOT / "tools" / "dyno-opt" / "dyno-ir" / "flow.dyno"
SCRIPT = DYNO_ROOT / "tools" / "dyno-opt" / "dyno-ir" / "script.dyno"
SIM_HARNESS = TEST_DIR / "sim_harness.dyno"
XILINX = DYNO_ROOT / "tools" / "dyno-opt" / "dyno-ir" / "xilinx"
SKY130 = DYNO_ROOT / "tools" / "dyno-opt" / "dyno-ir" / "sky130_fd_sc_hd.dyno"
EXAMPLE_MEMORIES = DYNO_ROOT / "tools" / "dyno-opt" / "dyno-ir" / "example_memories.dyno"
LIBERTY = DYNO_ROOT / "sky130_fd_sc_hd__tt_025C_1v80.lib"
SLANG = ["--allow-use-before-declare", "--single-unit", "--relax-enum-conversions", "--allow-hierarchical-const", "--allow-multi-driven-locals", "--std", "1800-2023", "--allow-toplevel-iface-ports", "--default-lifetime-automatic"]
DRY_RUN = False

MMIO_BASE = 0x10000000
HALT_ADDR = 0x90000000
CLOCK_ADDR = MMIO_BASE + 4

TECH = {
    "xilinx": {
        "flipflops": XILINX / "flipflops.dyno",
        "memories": XILINX / "memories.dyno",
        "flow": "flow_completeFlowFPGA_tgt_specific",
        "liberty": LIBERTY,
    },
    "sky130": {
        "flipflops": SKY130,
        "memories": EXAMPLE_MEMORIES,
        "flow": "flow_completeFlow_tgt_specific",
        "liberty": LIBERTY,
    },
}


def parse_error(log):
    path = Path(log)
    lines = path.read_text(errors="replace").splitlines() if path.exists() else []
    return next((line.strip() for line in lines if any(key in line for key in ("error:", "fatal", "unsupported"))), None)


def run(cmd, log, cwd, timeout):
    log = Path(log)
    log.parent.mkdir(parents=True, exist_ok=True)
    argv = shlex.split(cmd) if isinstance(cmd, str) else [str(x) for x in cmd]
    if DRY_RUN:
        print("CMD:", shlex.join(argv), flush=True)
        return {"status": "ok", "returncode": 0, "elapsed_s": 0.0, "log": str(log), "error": None, "dry_run": True}
    start = time.monotonic()
    try:
        with open(log, "w") as stream:
            proc = subprocess.run(argv, cwd=str(cwd), stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "returncode": 124, "elapsed_s": time.monotonic() - start, "log": str(log), "error": parse_error(log)}
    return {"status": "ok" if proc.returncode == 0 else "failed", "returncode": proc.returncode, "elapsed_s": time.monotonic() - start, "log": str(log), "error": parse_error(log) if proc.returncode else None}


def parse_cells(path, tech):
    if not Path(path).exists():
        return {}
    pattern = re.compile(r"^\s*(sky130_fd_sc_hd__\w+)") if tech == "sky130" else re.compile(r"^\s*(LUT\d+|FD\w+|RAM\w+|Constant\d+)")
    counts = Counter()
    for line in Path(path).read_text(errors="replace").splitlines():
        match = pattern.match(line)
        if match:
            counts[match.group(1)] += 1
    return dict(counts)


def write_script(path, lines):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    return path


def make_rtl_flow(work, top_regex, header="sim_header.h", design="design.dyno", top_name="Top"):
    text = SCRIPT.read_text()
    text = text.replace("test/SoomRV/sim/sim_header_golden.h", str(Path(work) / header))
    text = text.replace('"topName": "GTop"', f'"topName": "{top_name}"')
    text = text.replace('"path": "design.dyno"', f'"path": "{Path(work) / design}"')
    if top_regex:
        text = text.replace(
            "meta.CHECK_PASS\nDUMP_SIM_HEADER_PASS",
            f'meta.SELECT_MODULES_PASS map("regex": "{top_regex}")\nmeta.CHECK_PASS\nDUMP_SIM_HEADER_PASS',
        )
    return write_script(Path(work) / "rtl_flow.dyno", text.splitlines())


def make_gl_synth_flow(tech, work, top_regex):
    config = TECH[tech]
    return write_script(
        Path(work) / "gl_synth_flow.dyno",
        [
            'CALL symbol("flow_completeFlow_generic")',
            f'PARSE_DYNO_PASS map("path": "{config["flipflops"]}", "newModulesActive": "0")',
            f'PARSE_DYNO_PASS map("path": "{config["memories"]}", "newModulesActive": "0")',
            "meta.POPULATE_INLINE_CACHES_PASS",
            f'CALL symbol("{config["flow"]}")',
            f'meta.SELECT_MODULES_PASS map("regex": "{top_regex}")',
        ],
    )


def make_gl_sim_flow(tech, checkpoint, work, top_regex, header="sim_header.h", design="design2.dyno"):
    config = TECH[tech]
    text = SIM_HARNESS.read_text()
    replacements = {
        '"post_lower_cfg.dyno"': f'"{checkpoint}"',
        '"tools/dyno-opt/dyno-ir/xilinx/flipflops.dyno"': f'"{config["flipflops"]}"',
        '"tools/dyno-opt/dyno-ir/xilinx/memories.dyno"': f'"{config["memories"]}"',
        'meta.SELECT_MODULES_PASS map("regex": "Top")': f'meta.SELECT_MODULES_PASS map("regex": "{top_regex}")',
        'DUMP_SIM_HEADER_PASS map("path": "sim_header.h")': f'DUMP_SIM_HEADER_PASS map("path": "{Path(work) / header}")',
        'DUMP_PASS map("path": "design2.dyno")': f'DUMP_PASS map("path": "{Path(work) / design}")',
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return write_script(Path(work) / "gl_flow.dyno", text.splitlines())


def dyno_script(script, work, timeout, log=None):
    return run([DYNO_SV, "script", str(script), str(FLOW)], log or Path(work) / "script.log", work, timeout)


def build_testbench(harness, include_dir, out, work, timeout, log=None):
    cxx = os.environ.get("CXX", "clang++")
    cxxflags = shlex.split(os.environ.get("CXXFLAGS", ""))
    ldflags = shlex.split(os.environ.get("LDFLAGS", ""))
    return run([
        cxx, "-std=c++23", "-O2", "-fno-rtti", *cxxflags,
        "-I" + str(include_dir), "-I" + str(TEST_DIR), "-I" + str(DYNO_ROOT / "include"),
        "-I" + str(DYNO_ROOT / "tools/dyno-sim/include"), "-I" + str(DYNO_ROOT / "tools/dyno-sim/libfst/src"),
        str(harness), str(DYNO_BUILD / "lib/libcore.a"), str(DYNO_BUILD / "lib/libhw.a"),
        str(DYNO_BUILD / "tools/dyno-sim/libfst.a"), *ldflags, "-lz", "-lpthread", "-o", str(out),
    ], log or Path(work) / "tb_build.log", work, timeout)


def run_programs(binary, dyno, top, programs, default_cycles, timeout, work, summary_prefix=None, log_prefix="sim", cycle_cap=None, allow_partial=False):
    programs = list(programs)
    if not programs:
        return {"status": "failed", "programs": [], "summary": None, "error": "no programs"}
    results = []
    for program in programs:
        limit = program.get("cycles") or default_cycles
        if cycle_cap is not None:
            limit = min(limit, cycle_cap)
        log = Path(work) / f"{log_prefix}_{program['name']}.log"
        run_result = run([
            binary, dyno, str(limit), top,
            program["bin"], str(program["mmio"]), str(program["halt"]),
        ], log, work, timeout)
        text = log.read_text(errors="replace") if log.exists() else ""
        summary = next((line.strip() for line in text.splitlines() if line.startswith(summary_prefix)), None) if summary_prefix else None
        output = text.split("OUTPUT: ", 1)[1].strip() if "OUTPUT: " in text else ""
        if summary is None:
            run_result["status"] = "failed"
        else:
            failed = "failed=true" in summary
            partial = "partial=true" in summary
            if failed:
                run_result["status"] = "failed"
            elif partial:
                run_result["status"] = "partial" if allow_partial and program.get("benchmark") else "failed"
            else:
                run_result["status"] = "ok"
        results.append({**run_result, "name": program["name"], "summary": summary, "output": output, "cycles": limit, "benchmark": program.get("benchmark", False)})
    status = "ok" if all(result["status"] in ("ok", "partial") for result in results) else "failed"
    return {"status": status, "programs": results, "summary": results[-1]["summary"] if results else None}


def dyno_synth(flow, files, out, work, timeout, top=None, log=None, liberty=LIBERTY):
    cmd = [DYNO_SV, "synth", "--liberty", str(liberty)]
    if top:
        cmd.append("--top=" + str(top))
    cmd.extend(["-s=" + str(FLOW), "-s=" + str(flow)])
    cmd.extend(str(f) for f in files)
    if out:
        cmd.append("-o=" + str(out))
    cmd.extend("--Xslang=" + flag for flag in SLANG)
    return run(cmd, log or Path(work) / "synth.log", work, timeout)


def rtl_synth(files, work, top_regex, timeout, header="sim_header.h", design="design.dyno", top_name="Top"):
    flow = make_rtl_flow(work, top_regex, header, design, top_name)
    return dyno_synth(flow, files, None, work, timeout, top_regex, Path(work) / "rtl_synth.log", LIBERTY)


def gl_synth(tech, files, work, timeout, top_regex):
    flow = make_gl_synth_flow(tech, work, top_regex)
    out = Path(work) / f"{tech}.v"
    result = dyno_synth(flow, files, out, work, timeout, top_regex, Path(work) / f"gl_synth_{tech}.log", TECH[tech]["liberty"])
    cells = parse_cells(out, tech)
    result.update({"tech": tech, "netlist": str(out), "cells": cells, "cell_count": sum(cells.values())})
    return result


def generic_sim(name, files, top_regex, harness, programs, cycles, timeout, summary_prefix=None):
    work = DYNO_WORK / name
    work.mkdir(parents=True, exist_ok=True)
    result = rtl_synth(files, work, top_regex, timeout)
    if result["status"] != "ok":
        return result
    build = build_testbench(harness, work, work / "tb", work, timeout, work / "sim_build.log")
    if build["status"] != "ok":
        return build
    result = run_programs(work / "tb", work / "design.dyno", top_regex, programs, cycles, timeout, work, summary_prefix, "sim")
    result["phase"] = "sim_run"
    return result


def generic_gl_sim(name, checkpoint, tech, top_regex, harness, programs, cycles, timeout, summary_prefix=None):
    checkpoint = Path(checkpoint)
    if not checkpoint.exists():
        return {"status": "failed", "phase": "gl_synth", "error": f"missing checkpoint: {checkpoint}"}
    work = DYNO_WORK / name / "gl"
    work.mkdir(parents=True, exist_ok=True)
    flow = make_gl_sim_flow(tech, checkpoint, work, top_regex)
    result = dyno_script(flow, work, timeout, work / "gl_synth.log")
    if result["status"] != "ok":
        return result
    build = build_testbench(harness, work, work / "tb", work, timeout, work / "gl_build.log")
    if build["status"] != "ok":
        return build
    result = run_programs(work / "tb", work / "design2.dyno", top_regex, programs, cycles, timeout, work, summary_prefix, "gl", cycle_cap=cycles, allow_partial=True)
    result["phase"] = "gl_sim"
    return result


def compare_sims(rtl, gl):
    if not rtl.get("programs") or not gl.get("programs"):
        return {"status": "failed", "mismatches": []}
    rtl_by_name = {program["name"]: program for program in rtl["programs"]}
    mismatches = []
    for program in gl["programs"]:
        rtl_program = rtl_by_name.get(program["name"])
        if not rtl_program:
            mismatches.append({"name": program["name"], "reason": "missing rtl"})
            continue
        if program.get("status") == "partial":
            if program.get("benchmark"):
                continue
            mismatches.append({"name": program["name"], "reason": "partial"})
            continue
        if rtl_program.get("status") != "ok" or program.get("status") != "ok":
            mismatches.append({"name": program["name"], "reason": "status"})
            continue
        if rtl_program.get("output") != program.get("output"):
            mismatches.append({"name": program["name"]})
    return {"status": "ok" if not mismatches else "failed", "mismatches": mismatches}


def run_target(name, files, top, sim_top, harness, args, summary_prefix, programs, gl_programs=None):
    work = DYNO_WORK / name
    work.mkdir(parents=True, exist_ok=True)
    target = {"name": name, "synth": {}, "sim": {}, "gl_sim": {}}
    for tech in args.techs:
        tech_work = work / "synth" / tech
        tech_work.mkdir(parents=True, exist_ok=True)
        target["synth"][tech] = gl_synth(tech, files, tech_work, args.synth_timeout, top)
    primary = args.techs[0] if args.techs else "xilinx"
    checkpoint = work / "synth" / primary / "post_techmap.dyno"
    target["sim"] = generic_sim(name, files, sim_top, harness, programs, args.sim_cycles, args.sim_timeout, summary_prefix)
    target["gl_sim"] = generic_gl_sim(name, checkpoint, primary, sim_top, harness, gl_programs or programs, args.gl_cycles, args.gl_timeout, summary_prefix)
    target["comparison"] = compare_sims(target["sim"], target["gl_sim"])
    for sim in (target["sim"], target["gl_sim"]):
        for program in sim.get("programs", []):
            program.pop("output", None)
    return target
