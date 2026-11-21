import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
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
EXAMPLE_MEMORIES = (
    DYNO_ROOT / "tools" / "dyno-opt" / "dyno-ir" / "example_memories.dyno"
)
SLANG = [
    "--allow-use-before-declare",
    "--single-unit",
    "--relax-enum-conversions",
    "--allow-hierarchical-const",
    "--allow-multi-driven-locals",
    "--std",
    "1800-2023",
    "--allow-toplevel-iface-ports",
    "--default-lifetime-automatic",
]
DRY_RUN = False

MMIO_BASE = 0x10000000
HALT_ADDR = 0x90000000
CLOCK_ADDR = MMIO_BASE + 4

TECH = {
    "xilinx": {
        "flipflops": XILINX / "flipflops.dyno",
        "memories": XILINX / "memories.dyno",
        "flow": "flow_completeFlowFPGA_tgt_specific",
    },
    "sky130": {
        "flipflops": SKY130,
        "memories": EXAMPLE_MEMORIES,
        "flow": "flow_completeFlow_tgt_specific",
    },
}

_COLORS = {
    "ok": "\033[32m",
    "passed": "\033[32m",
    "failed": "\033[31m",
    "timeout": "\033[31m",
    "partial": "\033[33m",
}
_RESET = "\033[0m"


def status_text(status):
    label = "passed" if status == "ok" else status
    color = _COLORS.get(status)
    if color and not os.environ.get("NO_COLOR"):
        return f"{color}{label}{_RESET}"
    return label


def progress(message):
    if DRY_RUN:
        return
    print(message, file=sys.stderr, flush=True)


def phase(label, result, extra=None):
    elapsed = result.get("elapsed_s", 0.0)
    text = f"{label}: {elapsed:.1f}s"
    if extra:
        text += f", {extra}"
    if result.get("status") != "ok":
        text += f", {status_text(result.get('status'))}"
    progress(text)


def parse_error(log):
    path = Path(log)
    lines = path.read_text(errors="replace").splitlines() if path.exists() else []
    return next(
        (
            line.strip()
            for line in lines
            if any(key in line for key in ("error:", "fatal", "unsupported"))
        ),
        None,
    )


def run(cmd, log, cwd, timeout):
    log = Path(log)
    log.parent.mkdir(parents=True, exist_ok=True)
    argv = shlex.split(cmd) if isinstance(cmd, str) else [str(x) for x in cmd]
    if DRY_RUN:
        print("CMD:", shlex.join(argv), flush=True)
        return {
            "status": "ok",
            "returncode": 0,
            "elapsed_s": 0.0,
            "log": str(log),
            "error": None,
            "dry_run": True,
        }
    start = time.monotonic()
    try:
        with open(log, "w") as stream:
            proc = subprocess.run(
                argv,
                cwd=str(cwd),
                stdout=stream,
                stderr=subprocess.STDOUT,
                timeout=timeout,
            )
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "returncode": 124,
            "elapsed_s": time.monotonic() - start,
            "log": str(log),
            "error": parse_error(log),
        }
    return {
        "status": "ok" if proc.returncode == 0 else "failed",
        "returncode": proc.returncode,
        "elapsed_s": time.monotonic() - start,
        "log": str(log),
        "error": parse_error(log) if proc.returncode else None,
    }


def parse_cells(path, tech):
    if not Path(path).exists():
        return {}
    pattern = (
        re.compile(r"^\s*(sky130_fd_sc_hd__\w+)")
        if tech == "sky130"
        else re.compile(r"^\s*(LUT\d+|FD\w+|RAM\w+|Constant\d+)")
    )
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


def make_rtl_flow(
    work, top_regex, header="sim_header.h", design="design.dyno", top_name="Top"
):
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


def make_gl_sim_flow(
    tech, checkpoint, work, top_regex, header="sim_header.h", design="design2.dyno"
):
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


def dyno_script(script, work, timeout, log=None, label="GL checkpoint/harness"):
    result = run(
        [DYNO_SV, "script", str(script), str(FLOW)],
        log or Path(work) / "script.log",
        work,
        timeout,
    )
    phase(label, result)
    return result


def build_testbench(harness, include_dir, out, work, timeout, log=None, label="build"):
    cxx = os.environ.get("CXX", "clang++")
    cxxflags = shlex.split(os.environ.get("CXXFLAGS", ""))
    ldflags = shlex.split(os.environ.get("LDFLAGS", ""))
    result = run(
        [
            cxx,
            "-std=c++23",
            "-O2",
            "-fno-rtti",
            *cxxflags,
            "-I" + str(include_dir),
            "-I" + str(TEST_DIR),
            "-I" + str(DYNO_ROOT / "include"),
            "-I" + str(DYNO_ROOT / "tools/dyno-sim/include"),
            "-I" + str(DYNO_ROOT / "tools/dyno-sim/libfst/src"),
            str(harness),
            str(DYNO_BUILD / "lib/libcore.a"),
            str(DYNO_BUILD / "lib/libhw.a"),
            str(DYNO_BUILD / "tools/dyno-sim/libfst.a"),
            *ldflags,
            "-lz",
            "-lpthread",
            "-o",
            str(out),
        ],
        log or Path(work) / "tb_build.log",
        work,
        timeout,
    )
    phase(label, result)
    return result


def run_commands(
    items,
    work,
    timeout,
    log_prefix="test",
    workers=None,
    result_key="tests",
    progress_prefix=None,
    binary=None,
    dyno=None,
    top=None,
    default_cycles=None,
    cycle_cap=None,
    summary_prefix=None,
    allow_partial=False,
):
    commands = []
    for item in items:
        if "cmd" in item:
            commands.append(item)
            continue
        limit = item.get("cycles") or default_cycles
        if cycle_cap is not None:
            limit = min(limit, cycle_cap)
        commands.append(
            {
                "name": item["name"],
                "cmd": [
                    binary,
                    dyno,
                    str(limit),
                    top,
                    item["bin"],
                    str(item["mmio"]),
                    str(item["halt"]),
                ],
                "program": item,
                "cycles": limit,
                "summary_prefix": summary_prefix,
                "allow_partial": allow_partial,
            }
        )
    if not commands:
        return {
            "status": "failed",
            result_key: [],
            "summary": None,
            "error": "no commands",
        }
    work = Path(work)
    if workers is None:
        workers = int(os.environ.get("DYNO_WORKERS", "4"))
    workers = max(1, min(workers, os.cpu_count() or 1))
    progress_prefix = progress_prefix or log_prefix

    def run_one(index, command):
        name = command["name"]
        progress(f"{progress_prefix}: {index}/{len(commands)} {name}")
        log = work / f"{log_prefix}_{name}.log"
        job_work = work / f"{log_prefix}_{name}"
        if job_work.exists():
            shutil.rmtree(job_work)
        job_work.mkdir(parents=True)
        result = run(command["cmd"], log, job_work, timeout)
        text = log.read_text(errors="replace") if log.exists() else ""
        item = {
            "name": name,
            "index": index,
            "log": str(log),
            "returncode": result["returncode"],
            "elapsed_s": result["elapsed_s"],
        }
        program = command.get("program")
        if program:
            summary = (
                next(
                    (
                        line.strip()
                        for line in text.splitlines()
                        if line.startswith(command["summary_prefix"])
                    ),
                    None,
                )
                if command["summary_prefix"]
                else None
            )
            output = text.split("OUTPUT: ", 1)[1].strip() if "OUTPUT: " in text else ""
            if summary is None or "failed=true" in summary:
                status = "failed"
            elif "partial=true" in summary:
                status = (
                    "partial"
                    if command["allow_partial"] and program.get("benchmark")
                    else "failed"
                )
            else:
                status = "ok"
            item.update(
                {
                    "status": status,
                    "summary": summary,
                    "output": output,
                    "cycles": command["cycles"],
                    "benchmark": program.get("benchmark", False),
                }
            )
        else:
            mismatch_lines = text.count("mismatch")
            match = re.search(r"instret:\s+(\d+)", text)
            instret = int(match.group(1)) if match else None
            ok = (
                result["status"] == "ok"
                and mismatch_lines == 0
                and (
                    ("PASSED" in text and "FAILED" not in text)
                    if ("PASSED" in text or "FAILED" in text)
                    else instret is not None and instret > 0
                )
            )
            item.update(
                {"status": "ok" if ok else "failed", "mismatch_lines": mismatch_lines}
            )
            if instret is not None:
                item["instret"] = instret
        if result.get("error"):
            item["error"] = result["error"]
        instret = f", instret={item['instret']}" if "instret" in item else ""
        progress(
            f"{progress_prefix}: {index}/{len(commands)} {name}: "
            f"{status_text(item['status'])}{instret}, {item['elapsed_s']:.1f}s"
        )
        return item

    with ThreadPoolExecutor(max_workers=workers) as pool:
        items = list(pool.map(run_one, range(1, len(commands) + 1), commands))
    mismatch_lines = sum(item.pop("mismatch_lines", 0) for item in items)
    passed_count = sum(item["status"] == "ok" for item in items)
    status = (
        "ok" if all(item["status"] in ("ok", "partial") for item in items) else "failed"
    )
    summary = items[-1].get("summary")
    if summary is None:
        summary = f"{passed_count}/{len(items)} {'tests' if result_key == 'tests' else 'programs'} passed"
    return {
        "status": status,
        result_key: items,
        "summary": summary,
        "mismatch_lines": mismatch_lines,
    }


def dyno_synth(flow, files, out, work, timeout, top=None, log=None):
    cmd = [DYNO_SV, "synth"]
    if top:
        cmd.append("--top=" + str(top))
    cmd.extend(["-s=" + str(FLOW), "-s=" + str(flow)])
    cmd.extend(str(f) for f in files)
    if out:
        cmd.append("-o=" + str(out))
    cmd.extend("--Xslang=" + flag for flag in SLANG)
    return run(cmd, log or Path(work) / "synth.log", work, timeout)


def rtl_synth(
    files,
    work,
    top_regex,
    timeout,
    header="sim_header.h",
    design="design.dyno",
    top_name="Top",
    label="RTL elaboration",
):
    flow = make_rtl_flow(work, top_regex, header, design, top_name)
    result = dyno_synth(
        flow, files, None, work, timeout, top_regex, Path(work) / "rtl_synth.log"
    )
    phase(label, result)
    return result


def gl_synth(tech, files, work, timeout, top_regex):
    flow = make_gl_synth_flow(tech, work, top_regex)
    out = Path(work) / f"{tech}.v"
    result = dyno_synth(
        flow, files, out, work, timeout, top_regex, Path(work) / f"gl_synth_{tech}.log"
    )
    cells = parse_cells(out, tech)
    result.update(
        {
            "tech": tech,
            "netlist": str(out),
            "cells": cells,
            "cell_count": sum(cells.values()),
        }
    )
    extra = f"{result['cell_count']} cells" if result["status"] == "ok" else None
    phase(f"synth {tech}", result, extra)
    return result


def generic_sim(
    name, files, top_regex, harness, programs, cycles, timeout, summary_prefix=None
):
    work = DYNO_WORK / name
    work.mkdir(parents=True, exist_ok=True)
    result = rtl_synth(files, work, top_regex, timeout)
    if result["status"] != "ok":
        return result
    build = build_testbench(
        harness,
        work,
        work / "tb",
        work,
        timeout,
        work / "sim_build.log",
        label="sim build",
    )
    if build["status"] != "ok":
        return build
    result = run_commands(
        programs,
        work,
        timeout,
        log_prefix="sim",
        result_key="programs",
        progress_prefix="sim programs",
        binary=work / "tb",
        dyno=work / "design.dyno",
        top=top_regex,
        default_cycles=cycles,
        summary_prefix=summary_prefix,
        allow_partial=True,
    )
    result["phase"] = "sim_run"
    return result


def generic_gl_sim(
    name,
    checkpoint,
    tech,
    top_regex,
    harness,
    programs,
    cycles,
    timeout,
    summary_prefix=None,
):
    checkpoint = Path(checkpoint)
    if not checkpoint.exists():
        return {
            "status": "failed",
            "phase": "gl_synth",
            "error": f"missing checkpoint: {checkpoint}",
        }
    work = DYNO_WORK / name / "gl"
    work.mkdir(parents=True, exist_ok=True)
    flow = make_gl_sim_flow(tech, checkpoint, work, top_regex)
    result = dyno_script(
        flow, work, timeout, work / "gl_synth.log", label="GL checkpoint/harness"
    )
    if result["status"] != "ok":
        return result
    build = build_testbench(
        harness,
        work,
        work / "tb",
        work,
        timeout,
        work / "gl_build.log",
        label="gl build",
    )
    if build["status"] != "ok":
        return build
    result = run_commands(
        programs,
        work,
        timeout,
        log_prefix="gl",
        result_key="programs",
        progress_prefix="gl programs",
        binary=work / "tb",
        dyno=work / "design2.dyno",
        top=top_regex,
        default_cycles=cycles,
        cycle_cap=cycles,
        summary_prefix=summary_prefix,
        allow_partial=True,
    )
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


def run_target(
    name, files, top, sim_top, harness, args, summary_prefix, programs, gl_programs=None
):
    work = DYNO_WORK / name
    work.mkdir(parents=True, exist_ok=True)
    target = {"name": name, "synth": {}, "sim": {}, "gl_sim": {}}
    for tech in args.techs:
        tech_work = work / "synth" / tech
        tech_work.mkdir(parents=True, exist_ok=True)
        target["synth"][tech] = gl_synth(
            tech, files, tech_work, args.synth_timeout, top
        )
    primary = args.techs[0] if args.techs else "xilinx"
    checkpoint = work / "synth" / primary / "post_techmap.dyno"
    target["sim"] = generic_sim(
        name,
        files,
        sim_top,
        harness,
        programs,
        args.sim_cycles,
        args.sim_timeout,
        summary_prefix,
    )
    target["gl_sim"] = generic_gl_sim(
        name,
        checkpoint,
        primary,
        sim_top,
        harness,
        gl_programs or programs,
        args.gl_cycles,
        args.gl_timeout,
        summary_prefix,
    )
    target["comparison"] = compare_sims(target["sim"], target["gl_sim"])
    for sim in (target["sim"], target["gl_sim"]):
        for program in sim.get("programs", []):
            program.pop("output", None)
    return target
