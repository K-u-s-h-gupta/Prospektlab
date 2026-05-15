from __future__ import annotations


def fuse_scores(*scores: float) -> float:
    if not scores:
        return 0.0
    total = 0.0
    weight = 1.0
    for score in scores:
        total += weight * score
        weight *= 0.75
    return total
