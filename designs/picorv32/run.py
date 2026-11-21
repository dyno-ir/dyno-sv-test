import subprocess
from pathlib import Path

import infra
from programs import build_all, coremark, riscv_test_programs

NAME = "picorv32"
HERE = Path(__file__).resolve().parent
REPO = HERE / "picorv32"
PATCH = HERE / "patch"
TB = HERE / "tb.cpp"
TOP = "picorv32"
SIM_TOP = "picorv32"
CATEGORIES = ["rv32ui"]
EXCLUDE = ["ma_data", "fence_i"]
PROGRAMS = riscv_test_programs(
    CATEGORIES,
    EXCLUDE,
    arch="rv32i",
    extra_sources=[infra.PROGRAMS_DIR / "exit.S"],
)
PROGRAMS.append(coremark("rv32i", 10_000_000))


def apply_patch():
    if not REPO.exists():
        raise RuntimeError(f"missing picorv32 checkout: {REPO}")
    if infra.DRY_RUN:
        infra.run(
            ["git", "-C", str(REPO), "apply", str(PATCH)],
            REPO / "patch.log",
            REPO,
            60,
        )
        return
    applied = subprocess.run(
        ["git", "-C", str(REPO), "apply", "--reverse", "--check", str(PATCH)],
        capture_output=True,
    )
    if applied.returncode == 0:
        return
    check = subprocess.run(
        ["git", "-C", str(REPO), "apply", "--check", str(PATCH)],
        capture_output=True,
    )
    if check.returncode != 0:
        raise RuntimeError(check.stderr.decode(errors="replace").strip())
    subprocess.run(["git", "-C", str(REPO), "apply", str(PATCH)], check=True)


def run(args):
    apply_patch()
    work = infra.DYNO_WORK / NAME
    work.mkdir(parents=True, exist_ok=True)
    built, error = build_all(PROGRAMS, work, args.sim_timeout)
    if error:
        return {"name": NAME, "synth": {}, "sim": error}
    files = [str(REPO / "picorv32.v")]
    return infra.run_target(NAME, files, TOP, SIM_TOP, TB, args, "PICORV32 ", built)
