"""Analytic cache hit rates under Zipf popularity, valid up to N = 1e11 items.

Popularity of the item with rank i (1-based) among N items:  p_i = i^-s / H(N, s)
with the generalized harmonic number H(N, s) = sum_{i=1..N} i^-s.  s = 0 is uniform.

Two cache models (independent reference model, i.e. no temporal correlation):
  topc_hit(C, N, s): cache holds the C most popular items (ideal static / perfect LFU)
                     hit = H(C, s) / H(N, s)
  che_lru_hit(C, N, s): LRU via Che's approximation
                     find T with  sum_i (1 - exp(-p_i T)) = C
                     hit = sum_i p_i (1 - exp(-p_i T))
For s = 0 both give hit = C / N.

Distinct items per token (k > 1): a token selects k DISTINCT items (e.g. top-k experts), so a
hot item counts at most once per token. Item i then appears in a token with probability
   q_i = 1 - exp(-lam * p_i),   lam chosen so that sum_i q_i = k,
and the access distribution over items is q_i / k. Passing k applies this correction; without it
the formulas assume independent requests and overstate hit rates for s >= 1.2.
Large N is handled with Euler-Maclaurin (harmonic numbers) and log-spaced rank bins (Che).
"""
import math

import numpy as np

_EM_M = 2000  # exact summation up to this rank, Euler-Maclaurin tail beyond


def harmonic(n, s):
    """H(n, s) = sum_{i=1..n} i^-s for real n >= 1 (n rounded down)."""
    n = int(n)
    if n <= 0:
        return 0.0
    if n <= _EM_M:
        i = np.arange(1, n + 1, dtype=np.float64)
        return float(np.sum(i ** -s))
    m = _EM_M
    head = float(np.sum(np.arange(1, m, dtype=np.float64) ** -s))  # ranks 1..m-1
    # Euler-Maclaurin: sum_{i=m..n} f(i) ~ int_m^n f + (f(m)+f(n))/2 + (f'(n)-f'(m))/12
    if abs(s - 1.0) < 1e-12:
        integral = math.log(n / m)
    else:
        integral = (n ** (1 - s) - m ** (1 - s)) / (1 - s)
    f = lambda x: x ** -s
    fp = lambda x: -s * x ** (-s - 1)
    return head + integral + (f(m) + f(n)) / 2 + (fp(n) - fp(m)) / 12


def topc_hit(C, N, s, k=None):
    """Hit rate of a cache that pins the C hottest of N items (perfect LFU, stationary)."""
    if C <= 0:
        return 0.0
    if C >= N:
        return 1.0
    if s == 0:
        return C / N
    if k and k > 1:
        r, n, w = _weights(N, s, k)
        cum = np.cumsum(n)
        j = int(np.searchsorted(cum, C))              # bin containing rank C
        full = float(np.sum((n * w)[:j]))
        before = cum[j - 1] if j > 0 else 0.0
        return min(1.0, full + (C - before) * w[j])
    return harmonic(C, s) / harmonic(N, s)


def _weights(N, s, k):
    """Binned access weights per item with distinct-k-per-token correction (sum n*w = 1)."""
    r, n = _rank_bins(N)
    p = r ** -s
    p /= np.sum(n * p)
    if not k or k <= 1:
        return r, n, p
    lo, hi = 1e-9, 1e9
    for _ in range(200):                              # sum n (1 - exp(-lam p)) = k
        lam = math.sqrt(lo * hi)
        if np.sum(n * -np.expm1(-lam * p)) < k:
            lo = lam
        else:
            hi = lam
        if hi / lo < 1 + 1e-10:
            break
    q = -np.expm1(-math.sqrt(lo * hi) * p)
    return r, n, q / np.sum(n * q)


def _rank_bins(N, nbins=3000):
    """Log-spaced rank bins over 1..N: returns representative rank r_j and count n_j per bin."""
    exact = min(N, 1000)
    ranks = list(np.arange(1, exact + 1, dtype=np.float64))
    counts = [1.0] * exact
    if N > exact:
        edges = np.unique(np.floor(np.geomspace(exact + 1, N + 1, nbins)).astype(np.float64))
        lo, hi = edges[:-1], edges[1:]
        ranks += list(np.sqrt(lo * (hi - 1).clip(min=lo)))
        counts += list(hi - lo)
    return np.array(ranks), np.array(counts)


def che_lru_hit(C, N, s, k=None):
    """LRU hit rate, Che approximation, N up to ~1e11 (k: distinct items per token)."""
    if C <= 0:
        return 0.0
    if C >= N:
        return 1.0
    if s == 0:
        return C / N
    r, n, p = _weights(N, s, k)
    # occupancy(T) = sum n_j (1 - exp(-p_j T)) is increasing in T; bisection on log T
    lo, hi = 1e-3 / p.max(), 1e3 / p.min()
    for _ in range(200):
        mid = math.sqrt(lo * hi)
        occ = np.sum(n * -np.expm1(-p * mid))
        if occ < C:
            lo = mid
        else:
            hi = mid
        if hi / lo < 1 + 1e-9:
            break
    T = math.sqrt(lo * hi)
    return float(np.sum(n * p * -np.expm1(-p * T)))


if __name__ == "__main__":
    # self-check against brute force at N = 1e5
    N = 100_000
    for s in (0.5, 1.0, 1.2):
        i = np.arange(1, N + 1, dtype=np.float64)
        p = i ** -s / np.sum(i ** -s)
        bf = float(np.sum(p[:1000]))
        print(f"s={s}: topc(1000)={topc_hit(1000, N, s):.4f} brute={bf:.4f}  "
              f"che_lru(1000)={che_lru_hit(1000, N, s):.4f}  H(1e10)={harmonic(1e10, s):.3f}")
