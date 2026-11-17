"""Follow-up SSD tests (same O_DIRECT test file as ssd_bench.py, deleted afterwards).

1. Span test: 4 KiB random reads QD32 over the first 256 MiB, 1 GiB, 4 GiB, 8 GiB of the file.
   A DRAM-less controller keeps its logical-to-physical map in host memory (HMB, tens of MB);
   if IOPS fall as the span grows, map misses cost NAND reads.
2. Parallel submitters: P processes x QD each, summed IOPS. Shows whether one io_uring at QD32
   already saturates the drive or the block layer / one CPU limits it.

    python ssd_bench_extra.py            # 8 GiB file, about 3 minutes, writes out/ssd_bench_extra.json
    python ssd_bench_extra.py --quick    # 512 MiB file, 1 s runs (about 30 s)
"""
import argparse
import json
import subprocess
import time
from pathlib import Path

import ssd_bench as sb

GiB, MiB, KiB = 1024**3, 1024**2, 1024


def run(mode, bs, qd, sec, span=None):
    cmd = [str(sb.BENCH_BIN), str(sb.TEST_FILE), mode, str(bs), str(qd), str(sec)]
    if span:
        cmd.append(str(span))
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)


def parallel(nproc, bs, qd, sec):
    ps = [run("rand", bs, qd, sec) for _ in range(nproc)]
    rs = [json.loads(p.communicate()[0]) for p in ps]
    return {"procs": nproc, "bs": bs, "qd_each": qd, "iops_total": round(sum(r["iops"] for r in rs), 1),
            "GBps_total": round(sum(r["GBps"] for r in rs), 4),
            "lat_mean_us": round(sum(r["lat_mean_us"] for r in rs) / nproc, 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out", default=str(sb.OUT_DIR / "ssd_bench_extra.json"))
    a = ap.parse_args()
    size = 512 * MiB if a.quick else 8 * GiB
    spans = (64 * MiB, 128 * MiB, 256 * MiB, 512 * MiB) if a.quick else (256 * MiB, 1 * GiB, 4 * GiB, 8 * GiB)
    sec = 1 if a.quick else 5
    sb.build()
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    res = {"date": time.strftime("%Y-%m-%d %H:%M:%S"), "temp_c_start": sb.temp_c(), "quick": a.quick}
    try:
        res["create_write"] = sb.create_file(size)
        time.sleep(1 if a.quick else 5)
        res["span"] = []
        for rep in range(1 if a.quick else 2):
            for span in spans:
                r = json.loads(run("rand", 4096, 32, sec, span).communicate()[0])
                r["rep"] = rep
                res["span"].append(r)
                print(r, flush=True)
        res["parallel"] = []
        plan = ((1, 4096, 32), (4, 4096, 8)) if a.quick else \
            ((1, 4096, 32), (2, 4096, 32), (4, 4096, 32), (4, 4096, 8), (8, 4096, 16), (1, 65536, 32), (4, 65536, 8))
        for nproc, bs, qd in plan:
            r = parallel(nproc, bs, qd, sec)
            res["parallel"].append(r)
            print(r, flush=True)
    finally:
        if sb.TEST_FILE.exists():
            sb.TEST_FILE.unlink()
        res["test_file_deleted"] = not sb.TEST_FILE.exists()
        res["temp_c_end"] = sb.temp_c()
        out.write_text(json.dumps(res, indent=1))
        print("deleted:", res["test_file_deleted"])


if __name__ == "__main__":
    main()
