from pathlib import Path

import infra
from programs import build_all, coremark, riscv_test_programs

NAME = "cv32e40p"
HERE = Path(__file__).resolve().parent
REPO = HERE / "cv32e40p"
TB = HERE / "tb.cpp"
CLOCK_GATE = HERE / "clock_gate.sv"
TOP = "cv32e40p_top"
SIM_TOP = "cv32e40p_top"
CATEGORIES = ["rv32ui", "rv32um", "rv32uc"]
EXCLUDE = ["ma_data"]
GL_EXCLUDE = ["rv32um-mulh", "rv32um-mulhsu", "rv32um-mulhu"]
PROGRAMS = riscv_test_programs(
    CATEGORIES,
    EXCLUDE,
    arch="rv32imc_zicsr_zifencei",
    extra_sources=[infra.PROGRAMS_DIR / "exit.S"],
)
PROGRAMS.append(coremark("rv32imac", 1_500_000))

def source_files():
    manifest = REPO / "cv32e40p_manifest.flist"
    files = []
    for line in manifest.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("//") or line.startswith("+incdir+"):
            continue
        line = line.replace("${DESIGN_RTL_DIR}", str(REPO / "rtl"))
        if (
            "../sva/" in line
            or line.endswith("cv32e40p_tb_wrapper.sv")
            or line.endswith("cv32e40p_tracer_pkg.sv")
        ):
            continue
        files.append(line)
    files = [f for f in files if not f.endswith("cv32e40p_sim_clock_gate.sv")]
    files.append(str(CLOCK_GATE))
    return files


def run(args):
    if not REPO.exists():
        raise RuntimeError(f"missing cv32e40p checkout: {REPO}")
    work = infra.DYNO_WORK / NAME
    work.mkdir(parents=True, exist_ok=True)
    built, error = build_all(PROGRAMS, work, args.sim_timeout)
    if error:
        return {"name": NAME, "synth": {}, "sim": error}
    gl_built = [program for program in built if program["name"] not in GL_EXCLUDE]
    return infra.run_target(NAME, source_files(), TOP, SIM_TOP, TB, args, "CV32E40P ", built, gl_built)
