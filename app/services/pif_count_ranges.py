"""Shared count-range filters for firm directory queries."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import and_, or_


COUNT_RANGE_BOUNDS: dict[str, tuple[int, int | None]] = {
    "0-0": (0, 0),
    "1-5": (1, 5),
    "6-10": (6, 10),
    "11-25": (11, 25),
    "26-50": (26, 50),
    "51-100": (51, 100),
    "101+": (101, None),
}


def count_ranges_condition(count_expression: Any, ranges: Iterable[str] | None):
    """Return an OR condition for the selected non-overlapping count buckets."""
    selected = list(dict.fromkeys(str(value).strip() for value in (ranges or []) if str(value).strip()))
    predicates = []
    for value in selected:
        bounds = COUNT_RANGE_BOUNDS.get(value)
        if bounds is None:
            continue
        minimum, maximum = bounds
        predicates.append(
            count_expression >= minimum
            if maximum is None
            else and_(count_expression >= minimum, count_expression <= maximum)
        )
    return or_(*predicates) if predicates else None
