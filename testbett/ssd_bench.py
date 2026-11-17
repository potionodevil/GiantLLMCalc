"""SSD read micro-benchmark (page cache bypassed with O_DIRECT).

Uses ssd_bench.c (io_uring, O_DIRECT; built on first run with gcc and liburing) and a
pure-Python thread cross-check (os.preadv on an O_DIRECT fd, aligned mmap buffers).

Steps:
  1. Create a test file (default 8 GiB) next to this script. On btrfs, chattr +C (NOCOW) is set on the
     empty file, so btrfs neither compresses nor checksums it and O_DIRECT reads reach the device.
     Content is random (incompressible). Sequential O_DIRECT write speed is recorded on the way.
  2. Read tests: seq and rand, block sizes 4K..1M, queue depth 1..128.
     Required points (seq 1M, rand 4K/16K/64K/1M at QD1 and QD32) run 3 times, median reported.
  3. Python thread cross-check at 4K QD1 and 4K with 32 threads.
  4. Delete the test file (always, in a finally block).

The test file needs free space of its size; it is written once (wear: one full file write).

    python ssd_bench.py                 # full run, about 15 minutes, writes out/ssd_bench.json
    python ssd_bench.py --quick         # 512 MiB file, short runs, a few points (about 1 minute)
"""
import argparse
import json
import mmap
import os
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCH_BIN = HERE / "ssd_bench"
TEST_FILE = HERE / ".benchfile"
OUT_DIR = HERE / "out"
FILE_SIZE = 8 * 1024**3          # 8 GiB
CHUNK = 64 * 1024**2             # write chunk 64 MiB
KiB, MiB = 1024, 1024**2


def read_sys(p):
    try:
        return Path(p).read_text().strip()
    except OSError:
        return None


def temp_c():
    for p in sorted(Path("/sys/class/nvme/nvme0").glob("hwmon*/temp1_input")):
        v = read_sys(p)
        if v:
            return int(v) / 1000
    return None


def device_info():
    nv = Path("/sys/class/nvme/nvme0")
    dev = (nv / "device").resolve() if (nv / "device").exists() else None
    info = {
        "model": read_sys(nv / "model"),
        "firmware": read_sys(nv / "firmware_rev"),
        "hmb_enabled": read_sys(nv / "hmb"),
        "nvme_io_queues": read_sys(nv / "queue_count"),
        "scheduler": read_sys("/sys/block/nvme0n1/queue/scheduler"),
    }
    if dev:
        info["pcie_current_speed"] = read_sys(dev / "current_link_speed")
        info["pcie_current_width"] = read_sys(dev / "current_link_width")
        info["pcie_max_speed_device"] = read_sys(dev / "max_link_speed")
        info["pcie_bridge_max_speed"] = read_sys(dev.parent / "max_link_speed")
        try:
            info["controller"] = subprocess.run(["lspci", "-s", dev.name], capture_output=True,
                                                text=True).stdout.strip()
        except OSError:
            pass
    try:
        # PCIe 3.0+: 128b/130b encoding; PCIe 1/2: 8b/10b. Bytes/s per lane = GT/s * enc / 8
        gts = float(info["pcie_current_speed"].split()[0])
        lanes = int(info["pcie_current_width"])
        enc = 128 / 130 if gts >= 8 else 8 / 10
        info["pcie_raw_GBps"] = round(gts * 1e9 * enc / 8 * lanes / 1e9, 3)
    except (KeyError, TypeError, ValueError, AttributeError):
        info["pcie_raw_GBps"] = None
    return info


def create_file(size=FILE_SIZE):
    """Write `size` random bytes with O_DIRECT; return sequential write GB/s."""
    if TEST_FILE.exists():
        TEST_FILE.unlink()
    TEST_FILE.touch()
    subprocess.run(["chattr", "+C", str(TEST_FILE)], check=False, capture_output=True)
    attrs = subprocess.run(["lsattr", str(TEST_FILE)], capture_output=True, text=True).stdout.split()
    import numpy as np
    rng = np.random.default_rng(1234)
    chunk = min(CHUNK, size)
    buf = mmap.mmap(-1, chunk)                 # anonymous mmap is page aligned
    fd = os.open(TEST_FILE, os.O_WRONLY | os.O_DIRECT)
    t0 = time.perf_counter()
    written = 0
    try:
        while written < size:
            buf[:] = rng.bytes(chunk)
            n = os.write(fd, buf)
            assert n == chunk
            written += n
        os.fsync(fd)
    finally:
        os.close(fd)
    el = time.perf_counter() - t0
    # drop any cached pages of the file (O_DIRECT writes should leave none)
    fd = os.open(TEST_FILE, os.O_RDONLY)
    os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
    os.close(fd)
    return {"bytes": written, "seconds": round(el, 2), "GBps_incl_rng": round(written / el / 1e9, 3),
            "file_attrs": attrs[0] if attrs else None}


def build():
    if not BENCH_BIN.exists():
        subprocess.run(["gcc", "-O2", "-o", str(BENCH_BIN), str(HERE / "ssd_bench.c"), "-luring"],
                       check=True)


def run_c(mode, bs, qd, seconds):
    out = subprocess.run([str(BENCH_BIN), str(TEST_FILE), mode, str(bs), str(qd), str(seconds)],
                         capture_output=True, text=True, check=True).stdout
    r = json.loads(out)
    r["temp_c_after"] = temp_c()
    return r


def py_threads(bs, nthreads, seconds, size):
    """Python cross-check: nthreads x os.preadv on one O_DIRECT fd (QD = nthreads)."""
    fd = os.open(TEST_FILE, os.O_RDONLY | os.O_DIRECT)
    nblocks = size // bs
    deadline = time.perf_counter() + seconds
    counts, lats = [0] * nthreads, [[] for _ in range(nthreads)]

    def worker(k):
        import random
        rnd = random.Random(k)
        b = mmap.mmap(-1, bs)
        c, lat = 0, lats[k]
        while True:
            t = time.perf_counter()
            if t >= deadline:
                break
            os.preadv(fd, [b], rnd.randrange(nblocks) * bs)
            lat.append(time.perf_counter() - t)
            c += 1
        counts[k] = c

    t0 = time.perf_counter()
    th = [threading.Thread(target=worker, args=(k,)) for k in range(nthreads)]
    [t.start() for t in th]
    [t.join() for t in th]
    el = time.perf_counter() - t0
    os.close(fd)
    ops = sum(counts)
    all_l = sorted(x for l in lats for x in l)
    return {"bs": bs, "threads": nthreads, "iops": round(ops / el, 1),
            "GBps": round(ops * bs / el / 1e9, 4),
            "lat_p50_us": round(all_l[len(all_l) // 2] * 1e6, 2),
            "lat_mean_us": round(statistics.fmean(all_l) * 1e6, 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="512 MiB file, 1 s runs, few points")
    ap.add_argument("--out", default=str(OUT_DIR / "ssd_bench.json"))
    a = ap.parse_args()
    size = 512 * MiB if a.quick else FILE_SIZE
    sec_req, sec_sweep, sec_py, reps_n = (1, 1, 1, 1) if a.quick else (8, 5, 6, 3)
    build()
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    res = {"device": device_info(), "temp_c_start": temp_c(),
           "date": time.strftime("%Y-%m-%d %H:%M:%S"), "file_size": size, "quick": a.quick}
    try:
        print("creating test file ...", flush=True)
        res["create_write"] = create_file(size)
        print(res["create_write"], flush=True)
        time.sleep(1 if a.quick else 5)

        # Required points, repeated and interleaved so drift spreads over all points.
        req = [("seq", MiB, 1), ("seq", MiB, 32), ("seq", 128 * KiB, 32)]
        req += [("rand", bs, qd) for bs in (4 * KiB, 16 * KiB, 64 * KiB, MiB) for qd in (1, 32)]
        if a.quick:
            req = [("seq", MiB, 32), ("rand", 4 * KiB, 1), ("rand", 4 * KiB, 32)]
        reps = {k: [] for k in req}
        for rep in range(reps_n):
            for k in req:
                r = run_c(k[0], k[1], k[2], sec_req)
                reps[k].append(r)
                print(rep, r, flush=True)
        res["required"] = []
        for k, rs in reps.items():
            med = sorted(rs, key=lambda r: r["iops"])[len(rs) // 2]
            res["required"].append({**med, "iops_min": min(r["iops"] for r in rs),
                                    "iops_max": max(r["iops"] for r in rs)})

        # Queue-depth sweep (one run each)
        res["sweep"] = []
        sizes = (4 * KiB, 64 * KiB) if a.quick else (4 * KiB, 16 * KiB, 64 * KiB, 256 * KiB, MiB)
        qds = (1, 8, 32) if a.quick else (1, 2, 4, 8, 16, 32, 64, 128)
        for bs in sizes:
            for qd in qds:
                r = run_c("rand", bs, qd, sec_sweep)
                res["sweep"].append(r)
                print(r, flush=True)

        # Python cross-check
        res["python_threads"] = [py_threads(4 * KiB, 1, sec_py, size), py_threads(4 * KiB, 32, sec_py, size),
                                 py_threads(64 * KiB, 32, sec_py, size)]
        print(res["python_threads"], flush=True)
    finally:
        if TEST_FILE.exists():
            TEST_FILE.unlink()
        res["test_file_deleted"] = not TEST_FILE.exists()
        res["temp_c_end"] = temp_c()
        out.write_text(json.dumps(res, indent=1))
        print("wrote", out.name, "deleted:", res["test_file_deleted"])


if __name__ == "__main__":
    sys.exit(main())
