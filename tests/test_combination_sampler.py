from random import Random

import pytest

from ncss_harves.combination_sampler import decode_combination, sample_combinations


def test_decode_matches_cartesian_product_order():
    dimensions = (("北京", "上海"), ("全职", "实习"), ("国企", "民企"))

    assert decode_combination(dimensions, 0) == ("北京", "全职", "国企")
    assert decode_combination(dimensions, 7) == ("上海", "实习", "民企")


def test_decode_rejects_out_of_range_index():
    dimensions = (("北京", "上海"), ("全职", "实习"))

    with pytest.raises(IndexError, match="combination index out of range"):
        decode_combination(dimensions, 4)


@pytest.mark.parametrize(
    ("flat_index", "expected"),
    [
        (0, (0, 0, 0)),
        (1, (1, 0, 0)),
        (2, (0, 1, 0)),
        (5, (1, 2, 0)),
        (6, (0, 0, 1)),
        (35, (1, 2, 5)),
    ],
)
def test_decode_treats_first_dimension_as_least_significant(flat_index, expected):
    dimensions = (tuple(range(2)), tuple(range(3)), tuple(range(6)))

    assert decode_combination(dimensions, flat_index) == expected


def test_sample_uses_all_combinations_when_limit_is_larger():
    dimensions = (("北京", "上海"), ("全职", "实习"))

    sampled = sample_combinations(dimensions, 20, Random(7))

    assert set(sampled) == {
        ("北京", "全职"),
        ("北京", "实习"),
        ("上海", "全职"),
        ("上海", "实习"),
    }


def test_sample_selects_unique_limit_without_materializing_product():
    dimensions = (tuple(range(10_000)), tuple(range(10_000)))

    sampled = sample_combinations(dimensions, 5, Random(7))

    assert len(sampled) == len(set(sampled)) == 5


def test_sample_without_dimensions_returns_single_empty_combination():
    assert sample_combinations((), 5, Random(7)) == ((),)


def test_sample_rejects_empty_dimension():
    with pytest.raises(ValueError, match="combination dimensions must not be empty"):
        sample_combinations((("北京",), ()), 5, Random(7))


def test_sample_rejects_non_positive_limit():
    with pytest.raises(ValueError, match="limit must be positive"):
        sample_combinations((("北京",),), 0, Random(7))
