from pathlib import Path

import infra
from programs import build_all, coremark, riscv_test_programs

NAME = "serv"
HERE = Path(__file__).resolve().parent
REPO = HERE / "serv"
TB = HERE / "tb.cpp"
TOP = "serv_rf_top"
SIM_TOP = "serv_rf_top"
CATEGORIES = ["rv32ui"]
EXCLUDE = ["ma_data", "fence_i"]
GL_EXCLUDE = ["rv32ui-ld_st"]
PROGRAMS = riscv_test_programs(
    CATEGORIES,
    EXCLUDE,
    arch="rv32i",
    extra_sources=[infra.PROGRAMS_DIR / "exit.S"],
)
PROGRAMS.append(coremark("rv32i", 100_000))


def source_files():
    return [str(path) for path in sorted((REPO / "rtl").glob("*.v"))]


def run(args):
    if not REPO.exists():
        raise RuntimeError(f"missing serv checkout: {REPO}")
    work = infra.DYNO_WORK / NAME
    work.mkdir(parents=True, exist_ok=True)
    built, error = build_all(PROGRAMS, work, args.sim_timeout)
    if error:
        return {"name": NAME, "synth": {}, "sim": error}
    gl_built = [program for program in built if program["name"] not in GL_EXCLUDE]
    return infra.run_target(NAME, source_files(), TOP, SIM_TOP, TB, args, "SERV ", built, gl_built)
