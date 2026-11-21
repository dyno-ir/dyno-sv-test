import argparse
import json
import shutil
from pathlib import Path


def copy_log(log, workspace, out, seen):
    if not log:
        return
    src = Path(log)
    if not src.exists():
        return
    try:
        rel = src.relative_to(workspace)
    except ValueError:
        rel = Path(src.name)
    dest = out / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest not in seen:
        shutil.copy2(src, dest)
        seen.add(dest)


def collect(build, out, workspace):
    out.mkdir(parents=True, exist_ok=True)
    seen = set()
    for json_path in sorted(build.glob("bench_*.json")):
        try:
            data = json.loads(json_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        for target in data.get("targets", {}).values():
            for synth in target.get("synth", {}).values():
                if synth.get("status") != "ok":
                    copy_log(synth.get("log"), workspace, out, seen)
            for key in ("sim", "gl_sim"):
                sim = target.get(key)
                if not sim:
                    continue
                if sim.get("status") not in ("ok", "partial"):
                    copy_log(sim.get("log"), workspace, out, seen)
                for program in sim.get("programs", []):
                    if program.get("status") not in ("ok", "partial"):
                        copy_log(program.get("log"), workspace, out, seen)
                for test in sim.get("tests", []):
                    if test.get("status") != "ok":
                        copy_log(test.get("log"), workspace, out, seen)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", default="build")
    parser.add_argument("--out", default=None)
    parser.add_argument("--workspace", default=None)
    args = parser.parse_args()

    build = Path(args.build).resolve()
    workspace = Path(args.workspace).resolve() if args.workspace else build.parent
    out = Path(args.out).resolve() if args.out else build / "failed_logs"
    collect(build, out, workspace)


if __name__ == "__main__":
    main()
