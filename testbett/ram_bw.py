"""Read bandwidth of system RAM (streaming numpy reductions, several processes).

P processes each sum a 96 MB float32 array 12 times (numpy reduction, streaming read). Aggregate
GB/s = P x 12 x 96 MB / wall time of the slowest process. Total RAM < 1 GB. Other load on the
machine lowers the result, so the value is a lower bound.

    python ram_bw.py        # about 10 s, writes out/ram_bw.json
"""
import argparse
import json
import multiprocessing as mp
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
MB = 96
REPS = 12


def worker(_):
    a = np.ones(MB * 1024 * 1024 // 4, dtype=np.float32)
    a.sum()                                        # touch pages
    t = time.perf_counter()
    for _ in range(REPS):
        a.sum()
    return time.perf_counter() - t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE / "out" / "ram_bw.json"))
    a = ap.parse_args()
    out = []
    for P in (1, 2, 4, 8):
        with mp.Pool(P) as pool:
            ts = pool.map(worker, range(P))
        gbps = P * REPS * MB * 1.048576e6 / max(ts) / 1e9
        out.append({"processes": P, "GBps": round(gbps, 1)})
        print(out[-1], flush=True)
    path = Path(a.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
