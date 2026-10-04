"""Run complete suites in fresh processes with seeded order and retain diagnostic logs."""
import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--seed", type=int, default=100)
    parser.add_argument("--output", default="data/repeat-suite")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    directory = Path(args.output)
    directory.mkdir(parents=True, exist_ok=True)
    results = []
    def run(index):
        seed = args.seed + index
        start = time.monotonic()
        with (directory / f"seed-{seed}.log").open("w", encoding="utf-8") as log:
            process = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "tools.shuffle_order",
                                      f"--shuffle-seed={seed}"], stdout=log, stderr=subprocess.STDOUT,
                                     env={**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"})
        return {"seed": seed, "passed": process.returncode == 0, "seconds": round(time.monotonic() - start, 2)}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending = [pool.submit(run, index) for index in range(args.runs)]
        for future in as_completed(pending):
            entry = future.result()
            results.append(entry)
            (directory / "summary.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
            print(json.dumps(entry), flush=True)
    return 0 if all(x["passed"] for x in results) else 1


if __name__ == "__main__":
    sys.exit(main())
