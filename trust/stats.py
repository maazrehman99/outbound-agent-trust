"""Small-sample statistics, standard library only."""
import math
import random


def wilson(k, n, z=1.96):
    """95% Wilson interval for k successes out of n. Returns (low, high) as fractions."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def pass_hat_k(c, n, k):
    """tau-bench pass^k for one task: chance that k runs drawn from n (c clean) are all clean."""
    if k > n:
        raise ValueError("k > n")
    return math.comb(c, k) / math.comb(n, k)


def mcnemar_exact(b, c):
    """Two-sided exact McNemar p-value. b = failed before / passed after, c = passed before / failed after."""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(0, min(b, c) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def cohen_kappa(a, b):
    """Kappa for two equal-length label lists."""
    n = len(a)
    if n == 0:
        return float("nan")
    labels = set(a) | set(b)
    po = sum(x == y for x, y in zip(a, b)) / n
    pe = sum((a.count(l) / n) * (b.count(l) / n) for l in labels)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def bootstrap_diff(groups_before, groups_after, iters=5000, seed=7):
    """95% CI of (after - before) failure rate, resampling LEADS (runs of one lead stay together).
    groups_*: dict lead_id -> list of 0/1 failures."""
    ids = sorted(set(groups_before) & set(groups_after))
    if not ids:
        return (float("nan"), float("nan"))
    rnd = random.Random(seed)
    diffs = []
    for _ in range(iters):
        pick = [rnd.choice(ids) for _ in ids]
        b = [x for i in pick for x in groups_before[i]]
        a = [x for i in pick for x in groups_after[i]]
        diffs.append(sum(a) / len(a) - sum(b) / len(b))
    diffs.sort()
    return (diffs[int(0.025 * iters)], diffs[int(0.975 * iters)])


def pct(x):
    return f"{100 * x:.0f}%"


def rate(k, n):
    lo, hi = wilson(k, n)
    return f"{k}/{n} ({pct(k / n) if n else '-'}, 95% CI {pct(lo)}-{pct(hi)})"
