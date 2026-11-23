"""Small-count suppression for outputs that leave the clinic-approved environment.

The clinic has not given us its disclosure rule yet. Until it does, this module
applies a PROVISIONAL rule with the limit k = disclosure.min_cell_size:

 1. Primary: a patient count from 1 to k-1 is not shown ("<k").
 2. Complementary: in a set of counts that add up to a shown total, if only one
    count is suppressed, the next smallest count is also suppressed, so that the
    suppressed value cannot be found by subtraction. If the total itself is
    below k, every count in the set is suppressed.
 3. Chain: in a list of nested counts (each step is a subset of the step before),
    a step is suppressed when it differs from the last shown step by 1 to k-1.
 4. A percentage, median or quartile is not shown when its denominator or
    sample is below k, or when its numerator is suppressed.

This rule reduces risk. It does not prove that an output is safe to share.
The clinic must approve shared outputs.
"""

from __future__ import annotations

import pandas as pd


def primary(count, k: int) -> bool:
    return pd.notna(count) and 0 < int(count) < k


def suppress_partition(counts: list[int], k: int, total: int | None = None) -> list[bool]:
    """Return a mask (True = suppress) for counts that add up to a shown total."""
    total = sum(int(c) for c in counts) if total is None else int(total)
    if 0 < total < k:
        return [int(c) > 0 for c in counts]
    mask = [primary(c, k) for c in counts]
    if sum(mask) == 1:
        others = [(int(c), i) for i, c in enumerate(counts) if not mask[i] and int(c) > 0]
        if others:
            mask[min(others)[1]] = True
    return mask


def suppress_chain(counts: list[int], k: int) -> list[bool]:
    """Mask for nested counts (each value is a subset of the one before)."""
    mask, last_shown = [], None
    for c in counts:
        c = int(c)
        hide = primary(c, k) or (last_shown is not None and 0 < last_shown - c < k)
        mask.append(hide)
        if not hide:
            last_shown = c
    return mask


def label(k: int) -> str:
    return f"<{k}"
