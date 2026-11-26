from dataclasses import dataclass, field
from pathlib import Path

import infra

AS_FLAGS = ["-mabi=ilp32"]

RISCV_TESTS = infra.PROGRAMS_DIR / "riscv-tests"
RISCV_ISA = RISCV_TESTS / "isa"
RISCV_MACROS = RISCV_ISA / "macros" / "scalar"
RISCV_TEST_HEADER_DIR = infra.PROGRAMS_DIR

CC_FLAGS = ["-mabi=ilp32", "-nostdlib", "-ffreestanding", "-O2", "-include", "stddef.h"]


@dataclass
class Program:
    name: str
    sources: list[Path]
    entry: str = "0"
    linker: Path | None = None
    include: list[Path] = field(default_factory=list)
    defines: list[str] = field(default_factory=list)
    arch: str = "rv32i"
    mmio: int = infra.MMIO_BASE
    halt: int = infra.HALT_ADDR
    cycles: int | None = None
    benchmark: bool = False


def build(program, work, timeout):
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    objects = []
    for source in program.sources:
        source = Path(source)
        obj = work / f"{program.name}_{source.stem}.o"
        if source.suffix in (".c", ".cc", ".cpp"):
            command = [
                "riscv32-elf-gcc",
                *CC_FLAGS,
                f"-march={program.arch}",
                *[f"-D{define}" for define in program.defines],
                *[f"-I{path}" for path in program.include],
                "-c",
                str(source),
                "-o",
                str(obj),
            ]
        elif source.suffix == ".S":
            command = [
                "riscv32-elf-gcc",
                "-x",
                "assembler-with-cpp",
                f"-march={program.arch}",
                *AS_FLAGS,
                *[f"-D{define}" for define in program.defines],
                *[f"-I{path}" for path in program.include],
                "-c",
                str(source),
                "-o",
                str(obj),
            ]
        else:
            command = [
                "riscv32-elf-as",
                f"-march={program.arch}",
                *AS_FLAGS,
                *[f"-I{path}" for path in program.include],
                "-o",
                str(obj),
                str(source),
            ]
        result = infra.run(
            command, work / f"{program.name}_{source.stem}_as.log", work, timeout
        )
        if result["status"] != "ok":
            return None, result
        objects.append(obj)

    elf = work / f"{program.name}.elf"
    libgcc_log = work / f"{program.name}_libgcc.log"
    result = infra.run(
        [
            "riscv32-elf-gcc",
            f"-march={program.arch}",
            "-mabi=ilp32",
            "-print-libgcc-file-name",
        ],
        libgcc_log,
        work,
        timeout,
    )
    if result["status"] != "ok":
        return None, result
    libgcc = libgcc_log.read_text().strip() if libgcc_log.exists() else "<libgcc>"
    if program.linker:
        command = [
            "riscv32-elf-ld",
            "--no-relax",
            "-T",
            str(program.linker),
            "-e",
            program.entry,
            *objects,
            libgcc,
            "-o",
            str(elf),
        ]
    else:
        command = [
            "riscv32-elf-ld",
            "--no-relax",
            "-Ttext=0",
            "-e",
            program.entry,
            *objects,
            libgcc,
            "-o",
            str(elf),
        ]
    result = infra.run(command, work / f"{program.name}_ld.log", work, timeout)
    if result["status"] != "ok":
        return None, result

    binary = work / f"{program.name}.bin"
    result = infra.run(
        ["riscv32-elf-objcopy", "-O", "binary", str(elf), str(binary)],
        work / f"{program.name}_objcopy.log",
        work,
        timeout,
    )
    if result["status"] != "ok":
        return None, result
    return (
        infra.BuiltProgram(
            name=program.name,
            bin=str(binary),
            elf=str(elf),
            mmio=program.mmio,
            halt=program.halt,
            cycles=program.cycles,
            benchmark=program.benchmark,
        ),
        None,
    )


def build_all(programs, work, timeout):
    built = []
    for program in programs:
        result, error = build(program, work, timeout)
        if error:
            return None, error
        built.append(result)
    return built, None


def riscv_test_programs(
    categories,
    exclude,
    arch,
    extra_sources=None,
    linker=None,
    entry="mytest",
    include=None,
    mmio=infra.MMIO_BASE,
    halt=infra.HALT_ADDR,
    header_dir=RISCV_TEST_HEADER_DIR,
    cycles=1_000_000,
):
    programs = []
    exclude = set(exclude)
    for category in categories:
        for source in sorted((RISCV_ISA / category).glob("*.S")):
            test = source.stem
            if test in exclude:
                continue
            name = f"{category}-{test}"
            sources = [source]
            if extra_sources:
                sources.extend(extra_sources)
            programs.append(
                Program(
                    name,
                    sources,
                    entry=entry,
                    linker=linker,
                    include=[header_dir, RISCV_MACROS, *(include or [])],
                    defines=[
                        "TEST_FUNC_NAME=mytest",
                        f'TEST_FUNC_TXT="{test}"',
                        "TEST_FUNC_RET=mytest_ret",
                        f"MMIO_BASE={mmio}",
                        f"HALT_ADDR={halt}",
                    ],
                    arch=arch,
                    mmio=mmio,
                    halt=halt,
                    cycles=cycles,
                )
            )
    return programs


def coremark(arch, cycles):
    root = infra.PROGRAMS_DIR / "coremark"
    coremark = root / "coremark"
    return Program(
        "coremark",
        [
            root / "crt0.S",
            root / "coremark_port.c",
            root / "ee_printf.c",
            coremark / "core_list_join.c",
            coremark / "core_main.c",
            coremark / "core_matrix.c",
            coremark / "core_state.c",
            coremark / "core_util.c",
        ],
        entry="_start",
        linker=root / "link.ld",
        include=[coremark, coremark / "barebones"],
        defines=[
            "ITERATIONS=1",
            "HAS_FLOAT=0",
            'FLAGS_STR="-O2"',
            f"MMIO_BASE={infra.MMIO_BASE}",
            f"HALT_ADDR={infra.HALT_ADDR}",
        ],
        benchmark=True,
        arch=arch,
        cycles=cycles,
    )
