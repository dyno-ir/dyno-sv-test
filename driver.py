import argparse
import importlib.util
import json
import sys
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
DESIGNS = TEST_DIR / "designs"
sys.path.insert(0, str(TEST_DIR))

import infra


def discover_targets():
    return sorted(
        path.name
        for path in DESIGNS.iterdir()
        if path.is_dir() and (path / "run.py").exists()
    )


def load_target(name):
    path = DESIGNS / name / "run.py"
    spec = importlib.util.spec_from_file_location(f"dyno_sv_target_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def target_failed(target):
    for synth in target.get("synth", {}).values():
        if synth.get("status") != "ok":
            return True
    for key in ("sim", "gl_sim"):
        sim = target.get(key)
        if sim and sim.get("status") not in ("ok", "partial"):
            return True
    comparison = target.get("comparison")
    if comparison and comparison.get("status") != "ok":
        return True
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--targets", nargs="*")
    parser.add_argument(
        "--techs", nargs="*", default=["xilinx"], choices=["xilinx", "sky130"]
    )
    parser.add_argument("--synth-timeout", type=int, default=1800)
    parser.add_argument("--sim-timeout", type=int, default=3600)
    parser.add_argument("--gl-timeout", type=int, default=3600)
    parser.add_argument("--gl-checkpoint", default="post_techmap.dyno")
    parser.add_argument("--cosim-timeout", type=int, default=3600)
    parser.add_argument("--sim-cycles", type=int, default=100000)
    parser.add_argument("--gl-cycles", type=int, default=100000)
    parser.add_argument("--cosim-cycles", type=int, default=100000)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Print commands instead of executing them.")
    parser.add_argument("--out", default="bench.json", help="Write benchmark JSON to this file.")
    args = parser.parse_args()

    targets = discover_targets()
    if args.list:
        for name in targets:
            print(name)
        return 0

    selected = args.targets or targets
    infra.DRY_RUN = args.dry_run
    run = {"targets": {}}
    failed = False
    for name in selected:
        infra.progress(f"=== {name} ===")
        target = load_target(name).run(args)
        run["targets"][name] = target
        if not args.dry_run:
            if target_failed(target):
                infra.progress(f"result: {infra.status_text('failed')}")
                failed = True
            else:
                infra.progress(f"result: {infra.status_text('ok')}")
    if not args.dry_run:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(run, indent=2) + "\n")
        return 1 if failed else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
