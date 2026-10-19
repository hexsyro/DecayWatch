"""Shared statistical and similarity primitives for tool logics.

Stdlib-only, deterministic (no random sampling, no hash randomization), so
every report is reproducible byte-for-byte. Each helper documents the method
it implements and the minimum sample size it needs — tools must respect the
gates so small uploads don't produce noise findings.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from typing import Any

# ---------------------------------------------------------------------------
# Descriptive statistics
# ---------------------------------------------------------------------------

def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def stdev(values: list[float]) -> float | None:
    """Sample standard deviation (needs n >= 2)."""
    if len(values) < 2:
        return None
    avg = sum(values) / len(values)
    return math.sqrt(sum((v - avg) ** 2 for v in values) / (len(values) - 1))


def mad(values: list[float]) -> float | None:
    """Median absolute deviation — robust spread estimator."""
    med = median(values)
    if med is None:
        return None
    return median([abs(v - med) for v in values])


def modified_zscores(values: list[float]) -> list[float]:
    """MAD-based modified z-scores (Iglewicz & Hoaglin).

    Robust to the very outliers it detects, unlike mean-based z-scores.
    When MAD is 0 (majority of points identical), falls back to the mean
    absolute deviation so a lone extreme still scores; all-identical input
    yields 0.0s (no spread to measure against).
    """
    med = median(values)
    if med is None:
        return [0.0 for _ in values]
    spread = mad(values)
    if not spread:
        spread = sum(abs(v - med) for v in values) / len(values)
    if not spread:
        return [0.0 for _ in values]
    return [0.6745 * (v - med) / spread for v in values]


# ---------------------------------------------------------------------------
# Proportions and contingency tables
# ---------------------------------------------------------------------------

def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score 95% interval for a binomial proportion.

    Behaves sanely at the extremes (0/n, n/n) where the Wald interval fails.
    """
    if n <= 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def _gamma_p(a: float, x: float) -> float:
    """Regularized lower incomplete gamma P(a, x) (Numerical Recipes gser)."""
    if x <= 0:
        return 0.0
    gln = math.lgamma(a)
    ap = a
    term = 1.0 / a
    total = term
    for _ in range(1, 500):
        ap += 1
        term *= x / ap
        total += term
        if abs(term) < abs(total) * 1e-12:
            break
    return total * math.exp(-x + a * math.log(x) - gln)


def _gamma_q(a: float, x: float) -> float:
    """Regularized upper incomplete gamma Q(a, x) via continued fraction (gcf)."""
    if x <= 0:
        return 1.0
    gln = math.lgamma(a)
    b = x + 1.0 - a
    c, d = 1e30, 1.0 / b
    h = d
    for i in range(1, 500):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        d = 1e-30 if abs(d) < 1e-30 else d
        c = b + an / c
        c = 1e-30 if abs(c) < 1e-30 else c
        d = 1.0 / d
        delta = c * d
        h *= delta
        if abs(delta - 1.0) < 1e-12:
            break
    return math.exp(-x + a * math.log(x) - gln) * h


def chi_square_sf(statistic: float, dof: int) -> float:
    """Survival function (p-value) of the chi-square distribution."""
    if statistic <= 0 or dof <= 0:
        return 1.0
    if statistic < dof + 1:
        return 1.0 - _gamma_p(dof / 2.0, statistic / 2.0)
    return _gamma_q(dof / 2.0, statistic / 2.0)


def chi_square_gof(observed: Sequence[float], expected: Sequence[float]) -> tuple[float, int]:
    """Goodness-of-fit statistic and degrees of freedom."""
    stat = sum((o - e) ** 2 / e for o, e in zip(observed, expected, strict=False) if e > 0)
    return stat, max(len(observed) - 1, 1)


def chi_square_contingency(table: list[list[float]]) -> tuple[float, int]:
    """Pearson chi-square for an r x c contingency table."""
    rows = len(table)
    cols = len(table[0]) if rows else 0
    total = sum(sum(row) for row in table)
    if rows < 2 or cols < 2 or total <= 0:
        return 0.0, 1
    col_sums = [sum(table[r][c] for r in range(rows)) for c in range(cols)]
    row_sums = [sum(table[r]) for r in range(rows)]
    stat = 0.0
    for r in range(rows):
        for c in range(cols):
            exp = row_sums[r] * col_sums[c] / total
            if exp > 0:
                stat += (table[r][c] - exp) ** 2 / exp
    return stat, (rows - 1) * (cols - 1)


def ks_statistic(a: Sequence[float], b: Sequence[float]) -> float:
    """Two-sample Kolmogorov-Smirnov statistic (max CDF gap, in [0, 1])."""
    if not a or not b:
        return 0.0
    points = sorted(set(a) | set(b))
    na, nb = len(a), len(b)
    gap = 0.0
    for p in points:
        fa = sum(1 for v in a if v <= p) / na
        fb = sum(1 for v in b if v <= p) / nb
        gap = max(gap, abs(fa - fb))
    return gap


# ---------------------------------------------------------------------------
# Information theory / validation
# ---------------------------------------------------------------------------

def shannon_entropy(text: str) -> float:
    """Bits of entropy per character. English prose is about 4.0-4.7; random text 5+."""
    if not text:
        return 0.0
    counts: dict[str, int] = {}
    for ch in text:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(text)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def luhn_valid(digits: str) -> bool:
    """Luhn checksum — kills most false-positive credit-card matches."""
    clean = "".join(ch for ch in digits if ch.isdigit())
    if len(clean) < 13 or len(clean) > 19:
        return False
    total = 0
    for i, ch in enumerate(reversed(clean)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


# ---------------------------------------------------------------------------
# String similarity
# ---------------------------------------------------------------------------

def levenshtein(a: str, b: str, max_dist: int | None = None) -> int:
    """Edit distance with optional early exit above max_dist."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    if max_dist is not None and abs(len(a) - len(b)) > max_dist:
        return max_dist + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        row_min = i
        for j, cb in enumerate(b, 1):
            cost = prev[j - 1] if ca == cb else 1 + min(prev[j - 1], prev[j], cur[j - 1])
            cur.append(cost)
            row_min = min(row_min, cost)
        if max_dist is not None and row_min > max_dist:
            return max_dist + 1
        prev = cur
    return prev[-1]


def jaro_winkler(a: str, b: str) -> float:
    """Jaro-Winkler similarity in [0, 1]; rewards shared prefixes."""
    if a == b:
        return 1.0
    la, lb = len(a), len(b)
    if not la or not lb:
        return 0.0
    window = max(la, lb) // 2 - 1
    window = max(window, 0)
    a_matched = [False] * la
    b_matched = [False] * lb
    matches = 0
    for i in range(la):
        lo, hi = max(0, i - window), min(lb, i + window + 1)
        for j in range(lo, hi):
            if not b_matched[j] and a[i] == b[j]:
                a_matched[i] = b_matched[j] = True
                matches += 1
                break
    if not matches:
        return 0.0
    transpositions = 0
    k = 0
    for i in range(la):
        if a_matched[i]:
            while not b_matched[k]:
                k += 1
            if a[i] != b[k]:
                transpositions += 1
            k += 1
    transpositions //= 2
    jaro = (matches / la + matches / lb + (matches - transpositions) / matches) / 3.0
    prefix = 0
    for ca, cb in zip(a, b, strict=False):
        if ca == cb and prefix < 4:
            prefix += 1
        else:
            break
    return jaro + prefix * 0.1 * (1.0 - jaro)


# ---------------------------------------------------------------------------
# TF-IDF cosine similarity
# ---------------------------------------------------------------------------

class TfIdf:
    """Tiny TF-IDF vector space: sublinear TF, smoothed IDF, cosine scoring."""

    def __init__(self, docs: list[list[str]]) -> None:
        self.n = len(docs)
        df: dict[str, int] = {}
        for doc in docs:
            for term in set(doc):
                df[term] = df.get(term, 0) + 1
        self.idf = {t: math.log((1 + self.n) / (1 + c)) + 1.0 for t, c in df.items()}

    def vector(self, tokens: list[str]) -> dict[str, float]:
        tf: dict[str, int] = {}
        for tok in tokens:
            tf[tok] = tf.get(tok, 0) + 1
        return {t: (1.0 + math.log(c)) * self.idf[t] for t, c in tf.items() if t in self.idf}

    @staticmethod
    def cosine(a: dict[str, float], b: dict[str, float]) -> float:
        if not a or not b:
            return 0.0
        dot = sum(v * b.get(k, 0.0) for k, v in a.items())
        na = math.sqrt(sum(v * v for v in a.values()))
        nb = math.sqrt(sum(v * v for v in b.values()))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)


# ---------------------------------------------------------------------------
# MinHash LSH (near-duplicate search at scale)
# ---------------------------------------------------------------------------

def _minhash_seed(seed: int, shingle: str) -> int:
    digest = hashlib.sha256(f"{seed}:{shingle}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def minhash_signature(shingles: set[str], num_perm: int = 64) -> list[int]:
    """Deterministic MinHash signature (sha256-seeded permutations)."""
    if not shingles:
        return [2**64 - 1] * num_perm
    return [min(_minhash_seed(s, h) for h in shingles) for s in range(num_perm)]


def lsh_bands_for_threshold(threshold: float, num_perm: int = 64) -> tuple[int, int]:
    """Pick (bands, rows) so the LSH catch probability bends at threshold."""
    t = min(max(threshold, 0.2), 0.95)
    rows = max(1, min(8, round(math.log(0.5) / math.log(t))))
    bands = max(1, num_perm // rows)
    return bands, rows


def lsh_candidate_pairs(
    signatures: list[list[int]], bands: int, rows: int
) -> set[tuple[int, int]]:
    """Band-and-row LSH: index pairs sharing any identical band."""
    buckets: dict[tuple[int, tuple[int, ...]], list[int]] = {}
    for idx, sig in enumerate(signatures):
        for b in range(bands):
            key = (b, tuple(sig[b * rows : (b + 1) * rows]))
            buckets.setdefault(key, []).append(idx)
    pairs: set[tuple[int, int]] = set()
    for members in buckets.values():
        if len(members) > 1:
            for i in range(len(members)):
                for j in range(i + 1, len(members)):
                    a, b = members[i], members[j]
                    pairs.add((a, b) if a < b else (b, a))
    return pairs


# ---------------------------------------------------------------------------
# SimHash (coordinated-duplicate detection)
# ---------------------------------------------------------------------------

def simhash_fingerprint(tokens: list[str]) -> int:
    """64-bit SimHash: near-duplicate texts land within a small Hamming ball."""
    acc = [0] * 64
    for tok in tokens:
        h = int.from_bytes(hashlib.sha256(tok.encode("utf-8")).digest()[:8], "big")
        for bit in range(64):
            acc[bit] += 1 if (h >> bit) & 1 else -1
    out = 0
    for bit, val in enumerate(acc):
        if val > 0:
            out |= 1 << bit
    return out


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


# ---------------------------------------------------------------------------
# Changepoint detection (CUSUM + binary segmentation)
# ---------------------------------------------------------------------------

def cusum_changepoint(values: list[float]) -> tuple[int, float]:
    """Page's two-sided CUSUM: returns (split index, normalized magnitude).

    Magnitude is the mean shift in units of overall stdev — comparable across
    series. Needs n >= 4; returns (-1, 0.0) when there is no spread.
    """
    n = len(values)
    if n < 4:
        return -1, 0.0
    avg = sum(values) / n
    var = sum((v - avg) ** 2 for v in values) / n
    sd = math.sqrt(var)
    if sd == 0:
        return -1, 0.0
    cum, best, loc = 0.0, 0.0, -1
    for i, v in enumerate(values[:-1]):
        cum += (v - avg) / sd
        if abs(cum) > abs(best):
            best, loc = cum, i + 1
    # Magnitude: standardized mean shift across the split.
    left, right = values[:loc], values[loc:]
    shift = abs(sum(right) / len(right) - sum(left) / len(left)) / sd if loc > 0 else 0.0
    return loc, shift


def binary_segmentation(
    values: list[float], min_size: int = 5, min_shift: float = 1.0
) -> list[int]:
    """Recursively split a series at CUSUM changepoints (needs n >= 2*min_size)."""
    points: list[int] = []

    def _split(lo: int, hi: int) -> None:
        if hi - lo < 2 * min_size:
            return
        loc, shift = cusum_changepoint(values[lo:hi])
        if loc < 0 or shift < min_shift:
            return
        mid = lo + loc
        if mid - lo < min_size or hi - mid < min_size:
            return
        points.append(mid)
        _split(lo, mid)
        _split(mid, hi)

    _split(0, len(values))
    return sorted(points)


# ---------------------------------------------------------------------------
# Benford's law (fabricated-number screening)
# ---------------------------------------------------------------------------

BENFORD_EXPECTED = [math.log10(1 + 1 / d) for d in range(1, 10)]


def first_digit(value: float) -> int | None:
    v = abs(value)
    if v <= 0 or not math.isfinite(v):
        return None
    while v >= 10:
        v /= 10
    while v < 1:
        v *= 10
    return int(v)


def benford_chi_square(values: list[float]) -> tuple[float, int, int] | None:
    """Chi-square of first-digit distribution vs Benford (needs n >= 50)."""
    digits = [d for v in values if (d := first_digit(v)) is not None]
    if len(digits) < 50:
        return None
    observed = [sum(1 for d in digits if d == k) for k in range(1, 10)]
    expected = [BENFORD_EXPECTED[k] * len(digits) for k in range(9)]
    stat, dof = chi_square_gof(observed, expected)
    return stat, dof, len(digits)


def finding_envelope(
    severity: str, field: str | None, message: str, record_id: str | None, metadata: dict[str, Any]
) -> dict[str, Any]:
    """One shared finding shape for tools that don't need a custom builder."""
    return {
        "severity": severity,
        "field": field,
        "message": message,
        "record_id": record_id,
        "metadata": metadata,
    }
