"""Memory-bounded sampling for Cartesian filter combinations."""

from math import prod
from random import Random
from typing import Sequence, TypeVar


T = TypeVar("T")


def decode_combination(
    dimensions: Sequence[Sequence[T]], flat_index: int
) -> tuple[T, ...]:
    """Decode a row-major flattened index without materializing the product."""
    total = prod(len(items) for items in dimensions)
    if flat_index < 0 or flat_index >= total:
        raise IndexError("combination index out of range")

    positions: list[int] = []
    remainder = flat_index
    for items in dimensions:
        remainder, position = divmod(remainder, len(items))
        positions.append(position)
    return tuple(
        dimensions[index][position] for index, position in enumerate(positions)
    )


def sample_combinations(
    dimensions: Sequence[Sequence[T]], limit: int, random_source: Random
) -> tuple[tuple[T, ...], ...]:
    """Select unique Cartesian combinations using only ``O(limit)`` memory."""
    if limit <= 0:
        raise ValueError("limit must be positive")

    normalized = tuple(tuple(items) for items in dimensions)
    if any(not items for items in normalized):
        raise ValueError("combination dimensions must not be empty")

    total = prod(len(items) for items in normalized)
    indices = random_source.sample(range(total), min(limit, total))
    return tuple(decode_combination(normalized, index) for index in indices)
