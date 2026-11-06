"""Summarise evidence/wlroots-*.jsonl: failures per arm, Fisher exact, intervals."""

import json
import sys
from collections import Counter
from math import comb

rows = [json.loads(entry) for entry in open(sys.argv[1])]
stock_lib = None
libs = {
    a: Counter(tuple(r["wlroots"]) for r in rows if r["arm"] == a)
    for a in ("stock", "patched")
}
valid = [r for r in rows if r["ok"] is not None and len(libs and r["wlroots"]) == 1]
# integrity: each arm must use exactly one library, and the two must differ
arm_lib = {a: libs[a].most_common(1)[0][0] for a in libs}
valid = [r for r in valid if tuple(r["wlroots"]) == arm_lib[r["arm"]]]
n = {a: sum(r["arm"] == a for r in valid) for a in arm_lib}
f = {a: sum(r["arm"] == a and not r["ok"] for r in valid) for a in arm_lib}


def pmf(a, r1, c1, N):  # hypergeometric
    return comb(c1, a) * comb(N - c1, r1 - a) / comb(N, r1)


a, b = f["stock"], f["patched"]
r1, c1, N = n["stock"], a + b, n["stock"] + n["patched"]
p0 = pmf(a, r1, c1, N)
p = sum(
    pmf(x, r1, c1, N)
    for x in range(max(0, c1 - n["patched"]), min(r1, c1) + 1)
    if pmf(x, r1, c1, N) <= p0 * (1 + 1e-9)
)


def cp(k, m, alpha=0.05):  # Clopper-Pearson via bisection
    def cdf(x, p):
        return sum(comb(m, i) * p**i * (1 - p) ** (m - i) for i in range(x + 1))

    lo = 0.0 if k == 0 else None
    if lo is None:
        entry, h = 0.0, 1.0
        for _ in range(60):
            mid = (entry + h) / 2
            (h, entry) = (mid, entry) if 1 - cdf(k - 1, mid) > alpha / 2 else (h, mid)
        lo = h
    entry, h = 0.0, 1.0
    for _ in range(60):
        mid = (entry + h) / 2
        (entry, h) = (mid, h) if cdf(k, mid) > alpha / 2 else (entry, mid)
    return lo, entry


out = {
    "libs": {a: [list(k) + [v] for k, v in libs[a].items()] for a in libs},
    "valid": n,
    "failures": f,
    "invalid": sum(r["ok"] is None for r in rows),
    "fisher_two_sided_p": p,
    "ci95": {x: cp(f[x], n[x]) for x in n},
    "max_map_seconds": {
        x: max((r["map_seconds"] or 0) for r in valid if r["arm"] == x) for x in n
    },
}
print(json.dumps(out, indent=1))
