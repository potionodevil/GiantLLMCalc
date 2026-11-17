"""Cache simulation for mixture-of-experts expert caches (one layer, k distinct experts per token).

Access models:
  static  : fixed Zipf popularity with exponent s over items (s = 0 is uniform). Ranks are
            assigned to item ids by a random permutation.
  drift   : load-balanced MoE. Trained MoEs use load-balancing losses, so popularity averaged
            over a corpus is near uniform. Locally (within one document/topic) a few experts
            dominate. Model: Zipf(s_local = 1.0) whose rank permutation is redrawn every
            `redraw_every` tokens. Global popularity is uniform, local popularity is skewed.
  temporal reuse p: each item used by the previous token is used again with probability p;
            remaining slots are drawn from the popularity distribution (distinct within a token).
Policies: LRU (OrderedDict) and perfect LFU (frequency counts persist after eviction, heap with
lazy deletion). Hit rate is measured after a warm-up period.

Analytic cross-check: hitrate.topc_hit (ideal LFU) and hitrate.che_lru_hit (Che approximation),
both with the distinct-k-items-per-token correction.

    python cache_sim.py           # 2 geometries, 36 traces, about 10 s on 4 cores
    python cache_sim.py --quick   # E=256 only, shorter traces (about 2 s)
Outputs: out/cache_sim.json, out/cache_tables.md, out/cache_moe_E*.png
"""
import argparse
import heapq
import json
import multiprocessing as mp
from collections import OrderedDict
from pathlib import Path

import numpy as np

from hitrate import che_lru_hit, topc_hit

HERE = Path(__file__).resolve().parent
S_LIST = [0.0, 0.5, 0.8, 1.0, 1.2]
P_LIST = [0.0, 0.3, 0.6]


# ------------------------------------------------------------------------------- trace generation
def make_trace(n_items, k, tokens, s, p_reuse, regime, seed, redraw_every=256):
    """Return int32 array (tokens, k) of item ids."""
    rng = np.random.default_rng(seed)
    ranks = np.arange(1, n_items + 1, dtype=np.float64)
    w = ranks ** -(1.0 if regime == "drift" else s)
    w /= w.sum()
    cdf = np.cumsum(w)
    perm = rng.permutation(n_items)                       # rank -> item id
    out = np.empty((tokens, k), dtype=np.int32)
    prev = None
    for t in range(tokens):
        if regime == "drift" and t % redraw_every == 0:
            perm = rng.permutation(n_items)
        chosen = []
        if prev is not None and p_reuse > 0:
            keep = prev[rng.random(k) < p_reuse]
            chosen = list(keep)
        need = k - len(chosen)
        cs = set(chosen)
        while need > 0:
            cand = perm[np.minimum(np.searchsorted(cdf, rng.random(2 * need + 4)), n_items - 1)]
            for c in cand:
                if c not in cs:
                    cs.add(c)
                    chosen.append(c)
                    need -= 1
                    if need == 0:
                        break
        out[t] = chosen
        prev = out[t]
    return out


# ------------------------------------------------------------------------------- cache policies
def run_lru(trace, C, warm):
    cache, hits, acc = OrderedDict(), 0, 0
    flat = trace.reshape(-1)
    start = warm * trace.shape[1]
    for i, x in enumerate(flat.tolist()):
        if x in cache:
            cache.move_to_end(x)
            h = 1
        else:
            h = 0
            cache[x] = None
            if len(cache) > C:
                cache.popitem(last=False)
        if i >= start:
            hits += h
            acc += 1
    return hits / acc


def run_lfu(trace, C, warm, n_items):
    """Perfect LFU: counts for all items persist; evict the cached item with the lowest count."""
    cnt = np.zeros(n_items, dtype=np.int64)
    cached, heap, hits, acc = set(), [], 0, 0
    flat = trace.reshape(-1)
    start = warm * trace.shape[1]
    for i, x in enumerate(flat.tolist()):
        cnt[x] += 1
        c = int(cnt[x])
        if x in cached:
            h = 1
            heapq.heappush(heap, (c, x))
        else:
            h = 0
            if len(cached) >= C:
                while True:                               # pop stale entries lazily
                    cc, y = heapq.heappop(heap)
                    if y in cached and cc == cnt[y]:
                        cached.discard(y)
                        break
            cached.add(x)
            heapq.heappush(heap, (c, x))
        if len(heap) > 8 * C + 1024:                      # compact the heap
            heap = [(int(cnt[y]), y) for y in cached]
            heapq.heapify(heap)
        if i >= start:
            hits += h
            acc += 1
    return hits / acc


def job(args):
    """One (geometry, regime, s, p) trace, all cache sizes, both policies."""
    name, n_items, k, tokens, warm, s, p, regime, sizes, seed, redraw = args
    tr = make_trace(n_items, k, tokens, s, p, regime, seed, redraw)
    res = []
    for C in sizes:
        C = max(1, int(round(C)))
        res.append({"geom": name, "N": n_items, "k": k, "regime": regime, "s": s, "p": p, "C": C,
                    "frac": C / n_items, "lru": run_lru(tr, C, warm),
                    "lfu": run_lfu(tr, C, warm, n_items),
                    # analytic references (static popularity; for drift: static s=1 as a reference only)
                    "che_lru": che_lru_hit(C, n_items, 1.0 if regime == "drift" else s, k),
                    "topc": topc_hit(C, n_items, 1.0 if regime == "drift" else s, k)})
    return res


# ------------------------------------------------------------------------------- experiment plan
def plan(quick=False):
    jobs, seed = [], 1
    geoms = [  # name, items, k, tokens, warm, curve sizes
        ("moe_E256_k8", 256, 8, 12000, 2000, [8, 16, 32, 64, 128]),
        ("moe_E2048_k16", 2048, 16, 10000, 2000, [16, 32, 64, 128, 256, 512, 1024]),
    ]
    if quick:
        geoms = [("moe_E256_k8", 256, 8, 3000, 500, [8, 32, 128])]
    for name, n, k, T, W, sizes in geoms:
        for regime in ("static", "drift"):
            for s in (S_LIST if regime == "static" else [1.0]):
                for p in P_LIST:
                    jobs.append((name, n, k, T, W, s, p, regime, sizes, seed, 256))
                    seed += 1
    return jobs


# ------------------------------------------------------------------------------- plots and tables
def plots(rows, out_dir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    pal = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
    plt.rcParams.update({"font.size": 9, "axes.edgecolor": "#52514e", "axes.labelcolor": "#0b0b0b",
                         "xtick.color": "#52514e", "ytick.color": "#52514e", "axes.grid": True,
                         "grid.color": "#e4e3df", "grid.linewidth": 0.6, "figure.facecolor": "#fcfcfb",
                         "axes.facecolor": "#fcfcfb", "axes.spines.top": False, "axes.spines.right": False})
    for geom in sorted({r["geom"] for r in rows}):
        sub = [r for r in rows if r["geom"] == geom]
        N, k = sub[0]["N"], sub[0]["k"]
        title = f"MoE experts, E={N}, k={k} per token ({100 * k / N:.2g}% routed active)"
        fig, axes = plt.subplots(1, 3, figsize=(12, 4.6), sharey=True)
        ax = axes[0]
        for i, s in enumerate(S_LIST):
            for pol, ls in (("lru", "-"), ("lfu", "--")):
                pts = sorted((r["frac"], r[pol]) for r in sub if r["regime"] == "static" and r["s"] == s and r["p"] == 0.0)
                if pts:
                    x, y = zip(*pts)
                    ax.plot(np.array(x) * 100, y, ls, color=pal[i], lw=2, marker="o", ms=4,
                            label=f"s={s}" if pol == "lru" else None)
        ax.set_title("Static Zipf, p=0 (solid LRU, dashed LFU)", fontsize=9)
        ax.set_xscale("log"); ax.set_xlabel("cache size (% of items)"); ax.set_ylabel("hit rate")
        ax.legend(frameon=False, fontsize=7, loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=3)
        ax = axes[1]
        for s in (0.0, 1.0):
            for p in P_LIST:
                pts = sorted((r["frac"], r["lru"]) for r in sub if r["regime"] == "static" and r["s"] == s and r["p"] == p)
                if pts:
                    x, y = zip(*pts)
                    ax.plot(np.array(x) * 100, y, "-" if s == 0 else "--", color=pal[P_LIST.index(p)],
                            lw=2, marker="o", ms=4, label=f"s={s}, p={p}")
        ax.set_title("Temporal reuse p (LRU; solid s=0, dashed s=1)", fontsize=9)
        ax.set_xscale("log"); ax.set_xlabel("cache size (% of items)")
        ax.legend(frameon=False, fontsize=7, loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=2)
        ax = axes[2]
        for i, (reg, s, lab) in enumerate((("static", 0.0, "uniform (s=0)"), ("drift", 1.0, "load-balanced, local s=1"),
                                           ("static", 1.0, "static s=1"))):
            for pol, ls in (("lru", "-"), ("lfu", "--")):
                pts = sorted((r["frac"], r[pol]) for r in sub if r["regime"] == reg and r["s"] == s and r["p"] == 0.0)
                if pts:
                    x, y = zip(*pts)
                    ax.plot(np.array(x) * 100, y, ls, color=pal[i], lw=2, marker="o", ms=4,
                            label=lab if pol == "lru" else None)
        ax.set_title("Global popularity: uniform vs topic drift (dashed LFU)", fontsize=9)
        ax.set_xscale("log"); ax.set_xlabel("cache size (% of items)")
        ax.legend(frameon=False, fontsize=7, loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=1)
        fig.suptitle(title, fontsize=10)
        fig.tight_layout()
        fig.savefig(out_dir / f"cache_{geom}.png", dpi=150)
        plt.close(fig)


def tables(rows, out_dir):
    L = ["# Cache simulation tables (generated by cache_sim.py)\n",
         "Hit rate after warm-up. lru/lfu = simulated; che_lru/topc = analytic (static popularity, "
         "distinct-k correction; under drift the static s=1 value is shown as a reference).\n"]
    for geom in sorted({r["geom"] for r in rows}):
        sub = [r for r in rows if r["geom"] == geom]
        L.append(f"\n## {geom} (N={sub[0]['N']}, k={sub[0]['k']})\n")
        sizes = sorted({r["C"] for r in sub})
        L.append("| regime | s | p | policy | " + " | ".join(f"C={c} ({c/sub[0]['N']*100:.3g}%)" for c in sizes) + " |")
        L.append("|---|---|---|---|" + "---|" * len(sizes))
        for reg, s, p in sorted({(r["regime"], r["s"], r["p"]) for r in sub}):
            for pol in ("lru", "lfu", "che_lru", "topc"):
                if pol in ("che_lru", "topc") and p != 0.0:
                    continue
                vals = {r["C"]: r[pol] for r in sub if (r["regime"], r["s"], r["p"]) == (reg, s, p)}
                L.append(f"| {reg} | {s} | {p} | {pol} | " + " | ".join(f"{vals.get(c, float('nan')):.3f}" for c in sizes) + " |")
    (out_dir / "cache_tables.md").write_text("\n".join(L) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out", default=str(HERE / "out"))
    a = ap.parse_args()
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    jobs = plan(a.quick)
    print(f"{len(jobs)} traces", flush=True)
    with mp.Pool(4) as pool:                              # 4 workers keep memory < 1 GB
        rows = [r for rs in pool.imap_unordered(job, jobs) for r in rs]
    rows.sort(key=lambda r: (r["geom"], r["regime"], r["s"], r["p"], r["C"]))
    (out_dir / "cache_sim.json").write_text(json.dumps({"rows": rows}, indent=1))
    tables(rows, out_dir)
    plots(rows, out_dir)
    print((out_dir / "cache_tables.md").read_text()[:3000])


if __name__ == "__main__":
    main()
