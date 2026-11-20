import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import infra
from programs import RISCV_TESTS

NAME = "soomrv"
HERE = Path(__file__).resolve().parent
REPO = HERE / "SoomRV"
CATEGORIES = [
    "rv32mi", "rv32si", "rv32ua", "rv32uc",
]
EXCLUDE = [
    "rv32mi-p-instret_overflow",
    "rv32mi-p-pmpaddr",
]
TOP = "SoC"
AS_FLAGS = ["-mabi=ilp32", "-march=rv32imac_zicsr_zfinx_zba_zbb_zbs_zicbom_zifencei"]
EXCLUDE_SOURCES = {"src/Top.sv", "src/ExternalAXISim.sv", "src/ExternalBus.sv", "src/ExternalBusMem.sv", "src/FPU.sv", "src/FMul.sv", "src/FDiv.sv", "src/MemRTL2W.sv"}



def source_files():
    text = (REPO / "Makefile").read_text()
    start = text.index("SRC_FILES =")
    files = []
    for line in text[start:].splitlines()[1:]:
        line = line.strip()
        if not line:
            break
        if line.endswith("\\"):
            line = line[:-1].strip()
        if line.startswith("src/") and line.endswith(".sv"):
            if line not in EXCLUDE_SOURCES:
                files.append(str(REPO / line))
        elif line.endswith(".sv"):
            if line not in EXCLUDE_SOURCES:
                files.append(str(REPO / line))
    return files


def golden_sources():
    return source_files() + [str(REPO / "src/Top.sv"), str(REPO / "src/ExternalAXISim.sv")]


def step(cmd, log, cwd, timeout):
    result = infra.run(cmd, log, cwd, timeout)
    return result if result["status"] != "ok" else None


def build_riscv_isa_sim(work, timeout):
    repo = REPO / "riscv-isa-sim"
    libs = ["libriscv.a", "libsoftfloat.a", "libdisasm.a"]
    if all((repo / lib).exists() for lib in libs):
        return None
    base = "-Os -g0"
    extra = os.environ.get("CXXFLAGS", "")
    cxxflags = f"{base} {extra}".strip()
    cxx = os.environ.get("CXX", "clang++")
    error = step(
        ["./configure", f"CFLAGS={base}", f"CXXFLAGS={cxxflags}", f"CXX={cxx}", "LDFLAGS=",
         "--with-boost=no", "--with-boost-asio=no", "--with-boost-regex=no"],
        work / "riscv_configure.log",
        repo,
        timeout,
    )
    if error:
        return error
    return step(
        f"make -j {os.cpu_count() or 4} libriscv.a libsoftfloat.a libdisasm.a",
        work / "riscv_build.log",
        repo,
        timeout,
    )


def compile_cosim(work, timeout):
    build_dir = work / "build"
    if build_dir.exists():
        shutil.rmtree(build_dir)
    cxx = os.environ.get("CXX", "clang++")
    cxxflags = os.environ.get("CXXFLAGS", "")
    ldflags = os.environ.get("LDFLAGS", "")
    error = step(
        ["cmake", "-S", str(HERE), "-B", str(build_dir),
         f"-DCMAKE_CXX_COMPILER={cxx}",
         f"-DCMAKE_CXX_FLAGS={cxxflags}",
         f"-DCMAKE_EXE_LINKER_FLAGS={ldflags}",
         "-DCMAKE_BUILD_TYPE=RelWithDebInfo",
         f"-DSOOMRV_HEADERS_DIR={work}",
         f"-DDYNO_ROOT={infra.DYNO_ROOT}",
         f"-DDYNO_BUILD={infra.DYNO_BUILD}"],
        work / "cosim_cmake.log",
        work,
        timeout,
    )
    if error:
        return None, error
    error = step(
        f"cmake --build {build_dir} -j {os.cpu_count() or 4}",
        work / "cosim_build.log",
        work,
        timeout,
    )
    if error:
        return None, error
    return build_dir / "soomrv_cosim", None


def build_riscv_tests(work, timeout):
    repo = work / "riscv-tests"
    if repo.exists():
        shutil.rmtree(repo)
    repo.mkdir(parents=True)
    shutil.copytree(RISCV_TESTS / "isa", repo / "isa", symlinks=True,
                    ignore=shutil.ignore_patterns(".git"))
    shutil.copytree(RISCV_TESTS / "env", repo / "env", symlinks=True,
                    ignore=shutil.ignore_patterns(".git"))
    targets = []
    for category in CATEGORIES:
        for source in sorted((RISCV_TESTS / "isa" / category).glob("*.S")):
            target = f"{category}-p-{source.stem}"
            if target in EXCLUDE:
                continue
            targets.append(target)
    cmd = [
        "make", "-C", "isa", "XLEN=32",
        "RISCV_PREFIX=riscv32-elf-", "RISCV_GCC=riscv32-elf-gcc",
        "-j", str(os.cpu_count() or 4), *targets,
    ]
    error = step(cmd, work / "riscv_tests_build.log", repo, timeout)
    if error:
        return None, error
    return repo / "isa", None


def build_soomrv_program(work, timeout):
    entry = work / "entry.o"
    program = work / "virtual_mem.o"
    elf = work / "virtual_mem.elf"
    for source, obj, log in [
        (REPO / "test_programs/entry.s", entry, work / "virtual_mem_entry_as.log"),
        (REPO / "test_programs/virtual_mem.s", program, work / "virtual_mem_as.log"),
    ]:
        error = step(
            ["riscv32-elf-as", *AS_FLAGS, "-o", str(obj), str(source)],
            log,
            work,
            timeout,
        )
        if error:
            return None, error
    error = step(
        ["riscv32-elf-ld", "--no-warn-rwx-segments", "-T", str(REPO / "linker.ld"), str(entry), str(program), "-o", str(elf)],
        work / "virtual_mem_ld.log",
        work,
        timeout,
    )
    if error:
        return None, error
    return elf, None


def run_custom_tests(work, binary, args, timeout):
    elf, error = build_soomrv_program(work, timeout)
    if error:
        return {
            "name": "virtual_mem",
            "status": "failed",
            "returncode": error.get("returncode"),
            "log": error.get("log"),
            "mismatch_lines": 0,
            "instret": 0,
        }
    log = work / "test_virtual_mem.log"
    result = infra.run(
        [str(binary), "-i", str(work / "design.dyno"),
         "-m", str(work / "design2.dyno"),
         "-c", str(args.cosim_cycles), "-q", str(elf)],
        log,
        work,
        timeout,
    )
    text = log.read_text(errors="replace") if log.exists() else ""
    mismatch_lines = text.count("mismatch")
    cosim_error = "ERROR" in text or "COSIM ERROR" in text
    match = re.search(r"instret:\s+(\d+)", text)
    instret = int(match.group(1)) if match else 0
    status = "ok" if result["status"] == "ok" and not mismatch_lines and not cosim_error and instret > 0 else "failed"
    return {
        "name": "virtual_mem",
        "status": status,
        "returncode": result["returncode"],
        "log": str(log),
        "mismatch_lines": mismatch_lines,
        "instret": instret,
    }


def run_tests(work, binary, isa_dir, args, timeout):
    elves = [
        elf
        for category in CATEGORIES
        for elf in sorted(isa_dir.glob(f"{category}-p-*"))
        if elf.name not in EXCLUDE
    ]

    def run_one(elf):
        name = elf.name
        log = work / f"test_{name}.log"
        result = infra.run(
            [str(binary), "-i", str(work / "design.dyno"),
             "-m", str(work / "design2.dyno"),
             "-c", str(args.cosim_cycles), "-q", "-t", str(elf)],
            log,
            work,
            timeout,
        )
        text = log.read_text(errors="replace") if log.exists() else ""
        mismatch_lines = text.count("mismatch")
        passed = "PASSED" in text
        failed = "FAILED" in text or "ERROR" in text or result["status"] != "ok" or mismatch_lines > 0
        return {
            "name": name,
            "status": "ok" if passed and not failed else "failed",
            "returncode": result["returncode"],
            "log": str(log),
            "mismatch_lines": mismatch_lines,
        }

    tests = []
    if elves:
        workers = min(4, os.cpu_count() or 1)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            tests = list(pool.map(run_one, elves))
    tests.append(run_custom_tests(work, binary, args, timeout))
    mismatch_lines = sum(test.pop("mismatch_lines") for test in tests)
    passed_count = sum(test["status"] == "ok" for test in tests)
    status = "ok" if tests and passed_count == len(tests) else "failed"
    return {
        "status": status,
        "tests": tests,
        "summary": f"{passed_count}/{len(tests)} tests passed",
        "mismatch_lines": mismatch_lines,
        "max_cycles": args.cosim_cycles,
    }


def cosim(args, work):
    golden = infra.rtl_synth(
        golden_sources(),
        work,
        None,
        args.cosim_timeout,
        header="sim_header_golden.h",
        design="design.dyno",
        top_name="GTop",
    )
    if golden["status"] != "ok":
        return golden
    checkpoint = work / "synth" / "xilinx" / "post_lower_cfg.dyno"
    text = (HERE / "script_sim_harness.dyno").read_text()
    replacements = {
        '"sv/soomrv/': f'"{REPO}/src/',
        '"post_lower_cfg.dyno"': f'"{checkpoint}"',
        '"tools/dyno-opt/dyno-ir/xilinx/flipflops.dyno"': f'"{infra.XILINX / "flipflops.dyno"}"',
        '"tools/dyno-opt/dyno-ir/xilinx/memories.dyno"': f'"{infra.XILINX / "memories.dyno"}"',
        'DUMP_SIM_HEADER_PASS map("path": "sim_header.h")': f'DUMP_SIM_HEADER_PASS map("path": "{work / "sim_header.h"}")',
        'DUMP_PASS map("path": "design2.dyno")': f'DUMP_PASS map("path": "{work / "design2.dyno"}")',
    }
    for old_text, new_text in replacements.items():
        text = text.replace(old_text, new_text)
    harness = work / "harness.dyno"
    harness.write_text(text)
    error = step(
        f"{infra.DYNO_SV} script {harness} {infra.FLOW}",
        work / "harness.log",
        work,
        args.cosim_timeout,
    )
    if error:
        return error
    error = build_riscv_isa_sim(work, args.cosim_timeout)
    if error:
        return error
    binary, error = compile_cosim(work, args.cosim_timeout)
    if error:
        return error
    isa_dir, error = build_riscv_tests(work, args.cosim_timeout)
    if error:
        return error
    return run_tests(work, binary, isa_dir, args, args.cosim_timeout)


def run(args):
    work = infra.DYNO_WORK / NAME
    work.mkdir(parents=True, exist_ok=True)
    techs = list(args.techs)
    if "xilinx" not in techs:
        techs.append("xilinx")
    synth = {}
    for tech in techs:
        tech_work = work / "synth" / tech
        tech_work.mkdir(parents=True, exist_ok=True)
        synth[tech] = infra.gl_synth(tech, source_files(), tech_work, args.synth_timeout, TOP)
    return {"name": NAME, "synth": synth, "sim": cosim(args, work)}
