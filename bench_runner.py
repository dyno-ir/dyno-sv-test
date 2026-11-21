import argparse
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent


def busy_jiffies():
    with open("/proc/stat") as f:
        values = [int(x) for x in f.readline().split()[1:]]
    return sum(values) - values[3] - values[4]


def busy_cores(base, start):
    elapsed = time.monotonic() - start
    return (busy_jiffies() - base) / (elapsed * os.sysconf("SC_CLK_TCK"))


def wait_idle(seconds, margin, poll):
    idle = 0.0
    while idle < seconds:
        if os.getloadavg()[0] <= margin:
            idle += poll
        else:
            idle = 0.0
        time.sleep(poll)


def run_driver(cmd, cores, margin, poll):
    env = os.environ.copy()
    env["DYNO_WORKERS"] = "1"
    proc = subprocess.Popen(cmd, env=env, stderr=subprocess.PIPE, text=True, bufsize=1)
    allowed = os.cpu_count() or 1
    base = busy_jiffies()
    start = time.monotonic()

    def reset():
        nonlocal base, start
        base = busy_jiffies()
        start = time.monotonic()

    def reader():
        nonlocal allowed
        for line in proc.stderr:
            sys.stderr.write(line)
            sys.stderr.flush()
            if line.startswith("=== "):
                allowed = os.cpu_count() or 1
                reset()
            elif line.startswith(("sim programs", "gl programs", "tests:")):
                allowed = cores
                reset()
            elif line.startswith(("synth", "RTL", "GL checkpoint", "riscv-isa-sim build", "cosim build", "riscv-tests build")):
                allowed = os.cpu_count() or 1
                reset()

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    while proc.poll() is None:
        if busy_cores(base, start) > allowed + margin:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            thread.join(timeout=2)
            return None, "busy"
        time.sleep(poll)
    thread.join()
    return proc.returncode, None


def commit_and_push(out):
    try:
        rel = out.relative_to(REPO)
    except ValueError:
        print(f"not committing outside repo: {out}", file=sys.stderr)
        return
    git = ["git", "-C", str(REPO)]
    subprocess.run(git + ["add", "--", str(rel)], check=True)
    if subprocess.run(git + ["diff", "--cached", "--quiet", "--", str(rel)]).returncode == 0:
        return
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    subprocess.run(git + ["commit", "-m", f"bench: {stamp}", "--", str(rel)], check=True)
    subprocess.run(git + ["push"], check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--targets", nargs="*")
    parser.add_argument("--out", default="bench_results/bench.json")
    parser.add_argument("--idle-seconds", type=int, default=3600)
    parser.add_argument("--cores", type=int, default=1)
    parser.add_argument("--margin", type=float, default=0.5)
    parser.add_argument("--poll", type=float, default=60)
    args = parser.parse_args()

    out = Path(args.out)
    if not out.is_absolute():
        out = REPO / out
    out = out.resolve()
    cmd = [sys.executable, str(REPO / "driver.py"), "--out", str(out)]
    if args.targets:
        cmd.extend(["--targets", *args.targets])

    while True:
        wait_idle(args.idle_seconds, args.margin, args.poll)
        rc, reason = run_driver(cmd, args.cores, args.margin, args.poll)
        if rc == 0:
            break
        if reason != "busy":
            return rc
        print("not idle; retrying", file=sys.stderr)
    commit_and_push(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
