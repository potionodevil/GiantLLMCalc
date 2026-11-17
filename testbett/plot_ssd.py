"""Plot the queue-depth sweep of ssd_bench.py: random-read IOPS and GB/s per block size.

    python plot_ssd.py out/ssd_bench.json out/ssd_qd_sweep.png
"""
import json
import sys

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

PAL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
plt.rcParams.update({"font.size": 9, "axes.edgecolor": "#52514e", "axes.labelcolor": "#0b0b0b",
                     "xtick.color": "#52514e", "ytick.color": "#52514e", "axes.grid": True,
                     "grid.color": "#e4e3df", "grid.linewidth": 0.6, "figure.facecolor": "#fcfcfb",
                     "axes.facecolor": "#fcfcfb", "axes.spines.top": False, "axes.spines.right": False})


def main(src, dst):
    j = json.loads(open(src).read())
    sw = j["sweep"]
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6), sharex=True)
    for i, bs in enumerate(sorted({r["bs"] for r in sw})):
        pts = sorted((r["qd"], r["iops"], r["GBps"]) for r in sw if r["bs"] == bs)
        qd, iops, gbs = zip(*pts)
        lab = f"{bs // 1024} KiB" if bs < 1 << 20 else f"{bs >> 20} MiB"
        axes[0].plot(qd, np.array(iops) / 1e3, "-o", color=PAL[i % len(PAL)], lw=2, ms=4, label=lab)
        axes[1].plot(qd, gbs, "-o", color=PAL[i % len(PAL)], lw=2, ms=4, label=lab)
    axes[0].set_ylabel("random read IOPS (thousands)"); axes[0].set_yscale("log")
    axes[1].set_ylabel("random read GB/s")
    raw = j["device"].get("pcie_raw_GBps")
    if raw:
        axes[1].axhline(raw, color="#52514e", lw=1, ls=":")
        axes[1].text(1, raw * 0.93, f"PCIe raw {raw:.2f} GB/s", fontsize=8, color="#52514e")
    for ax in axes:
        ax.set_xscale("log", base=2); ax.set_xlabel("queue depth (one io_uring, O_DIRECT)")
    axes[0].legend(frameon=False, fontsize=8, title="block size", title_fontsize=8)
    model = j["device"].get("model") or "NVMe"
    fig.suptitle(f"{model}, {j['file_size'] / 2**30:.3g} GiB file, page cache bypassed", fontsize=10)
    fig.tight_layout()
    fig.savefig(dst, dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    main(*sys.argv[1:3])
