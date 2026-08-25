import pytest

from ncss_harves.areas import PROVINCE_AREA_CODES
from ncss_harves.errors import InvalidFilter
from ncss_harves.filters import (
    COMPANY_TYPE_VALUES,
    DEGREE_NATIVE_VALUES,
    MONTH_PAY_NATIVE_VALUES,
    PROPERTY_VALUES,
    RECRUIT_TYPE_VALUES,
    SOURCE_NATIVE_VALUES,
    crawl_request_from_params,
)
from ncss_harves.models import Query


def test_query_uses_one_based_page_and_readable_job_type():
    query = Query.from_params({"jobType": "工作", "offset": "2", "limit": "50"})

    assert query.job_types == ("全职",)
    assert query.page == 2
    assert query.limit == 50
    assert query.row_offset == 50


def test_query_accepts_chinese_commas_and_removes_duplicates():
    query = Query.from_params({"areaName": "北京，上海,北京", "jobType": "实习,兼职"})

    assert query.area_names == ("北京", "上海")
    assert query.job_types == ("实习", "兼职")


def test_query_accepts_province_short_name_and_official_city_name():
    query = Query.from_params({"areaName": "浙江,温州市"})

    assert query.area_names == ("浙江", "温州市")


def test_crawl_translates_official_city_name_to_native_area_code():
    request = crawl_request_from_params({"areaName": "温州市"})

    assert request.dimensions == (((("areaCode", "330300"),),),)


def test_explicit_province_and_city_multiselect_keeps_both_options():
    request = crawl_request_from_params({"areaName": "浙江,嘉兴市"})

    assert request.dimensions[0] == (
        (("areaCode", "33"),),
        (("areaCode", "330400"),),
    )


@pytest.mark.parametrize("value", ["杭州", "温州", "长春"])
def test_area_filter_rejects_short_city_aliases(value):
    with pytest.raises(InvalidFilter):
        Query.from_params({"areaName": value})
    with pytest.raises(InvalidFilter):
        crawl_request_from_params({"areaName": value})


@pytest.mark.parametrize("value", [None, "", "全部", "不限"])
def test_all_labels_mean_no_filter(value):
    query = Query.from_params({"degreeName": value, "companyType": value})

    assert query.degree_names == ()
    assert query.company_types == ()


def test_query_rejects_unknown_readable_value_with_allowed_values():
    with pytest.raises(InvalidFilter) as caught:
        Query.from_params({"jobType": "临时工"})

    assert caught.value.dimension == "jobType"
    assert caught.value.value == "临时工"
    assert "实习" in caught.value.allowed_values


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"offset": 0}, "offset must be between 1 and"),
        ({"limit": 101}, "limit must be between 1 and 100"),
        ({"random": "sometimes"}, "invalid boolean"),
    ],
)
def test_query_rejects_invalid_pagination_and_boolean(params, message):
    with pytest.raises(ValueError, match=message):
        Query.from_params(params)


def test_query_accepts_industry_group_and_detail_labels():
    query = Query.from_params(
        {"industrySectors": "互联网/通信/电子,计算机软件", "categoryName": "经营管理类"}
    )

    assert query.industry_names == ("互联网/通信/电子", "计算机软件")
    assert query.category_names == ("经营管理类",)


def test_crawl_request_translates_readable_filters():
    request = crawl_request_from_params(
        {
            "jobName": "算法",
            "areaName": "北京",
            "degreeName": "本科",
            "categoryName": "计算机/网络/技术类",
            "industrySectors": "互联网/电子商务",
            "jobType": "实习",
            "property": "国有企业",
            "companyType": "重点领域",
            "monthPay": "10K-15K",
            "recruitType": "职位",
            "sourceName": "智联招聘",
            "offset": "7",
            "limit": "40",
        }
    )

    assert request.page == 7
    assert request.limit == 40
    combination = tuple(dimension[0] for dimension in request.dimensions)
    assert request.native_params(combination) == {
        "jobName": "算法",
        "offset": 7,
        "limit": 40,
        "monthPay": "10-15",
        "areaCode": "11",
        "jobType": "03",
        "keyUnits": "1",
        "degreeCode": "31",
        "categoryCode": "01",
        "industrySectors": "000104,",
        "property": "国有企业",
        "recruitType": "0",
        "sourcesName": "fawzqa3wo3hy2x4uqe1b1bwy4met2wpb",
        "sourcesType": "0",
    }


def test_crawl_industry_group_expands_to_native_detail_codes():
    request = crawl_request_from_params({"industrySectors": "金融"})
    combination = (request.dimensions[0][0],)
    assert request.native_params(combination)["industrySectors"] == (
        "000201,000202,000203,000204,000205,"
    )


def test_crawl_request_preserves_native_combination_dimensions():
    request = crawl_request_from_params(
        {
            "areaName": "北京,上海",
            "jobType": ["全职", "实习"],
            "companyType": "重点领域,精选企业",
            "degreeName": "本科,硕士",
            "monthPay": "10K-15K",
            "limit": "5",
        }
    )

    assert [len(items) for items in request.dimensions] == [2, 2, 2, 2]
    assert request.common_items == (("monthPay", "10-15"),)
    assert request.native_params(
        (
            request.dimensions[0][0],
            request.dimensions[1][1],
            request.dimensions[2][0],
            request.dimensions[3][1],
        ),
        limit=3,
    ) == {
        "jobName": "",
        "offset": 1,
        "limit": 3,
        "monthPay": "10-15",
        "areaCode": "11",
        "jobType": "03",
        "keyUnits": "1",
        "degreeCode": "11",
    }


def test_crawl_industry_native_value_has_trailing_comma():
    request = crawl_request_from_params(
        {"industrySectors": "计算机软件,计算机硬件"}
    )

    assert request.dimensions[0] == (
        (("industrySectors", "000101,"),),
        (("industrySectors", "000102,"),),
    )


@pytest.mark.parametrize(
    ("label", "native"),
    [
        ("大专", "41"),
        ("本科", "31"),
        ("硕士", "11"),
        ("博士", "01"),
    ],
)
def test_crawl_degree_uses_native_code(label, native):
    request = crawl_request_from_params({"degreeName": label})

    assert request.dimensions == (((("degreeCode", native),),),)


@pytest.mark.parametrize(
    ("label", "native"),
    [
        ("2K以下", "2"),
        ("2K-5K", "2-5"),
        ("5K-10K", "5-10"),
        ("10K-15K", "10-15"),
        ("15K-25K", "15-25"),
        ("25K-50K", "25-50"),
        ("50K以上", "50"),
        ("面议", "0"),
    ],
)
def test_crawl_month_pay_uses_readable_enum(label, native):
    request = crawl_request_from_params({"monthPay": label})

    assert request.common_items == (("monthPay", native),)


def test_crawl_explicit_month_pay_multiselect_becomes_ordered_dimension():
    request = crawl_request_from_params(
        {"monthPay": "2K以下,面议,2K以下"}
    )

    assert request.common_items == ()
    assert request.dimensions == (
        (
            (("monthPay", "2"),),
            (("monthPay", "0"),),
        ),
    )


def test_crawl_rejects_unknown_month_pay():
    with pytest.raises(InvalidFilter) as caught:
        crawl_request_from_params({"monthPay": "8k-12k"})

    assert caught.value.dimension == "monthPay"


@pytest.mark.parametrize(
    ("field", "expected_count"),
    [
        ("areaName", len(PROVINCE_AREA_CODES)),
        ("degreeName", len(DEGREE_NATIVE_VALUES)),
        ("monthPay", len(MONTH_PAY_NATIVE_VALUES)),
        ("jobType", 3),
        ("property", len(PROPERTY_VALUES)),
        ("companyType", len(COMPANY_TYPE_VALUES)),
        ("recruitType", len(RECRUIT_TYPE_VALUES)),
        ("sourceName", len(SOURCE_NATIVE_VALUES)),
    ],
)
def test_crawl_random_expands_complete_native_dimension(field, expected_count):
    request = crawl_request_from_params({field: "random"})

    assert len(request.dimensions) == 1
    assert len(request.dimensions[0]) == expected_count
    assert len(set(request.dimensions[0])) == expected_count


def test_crawl_random_dominates_explicit_values():
    request = crawl_request_from_params(
        {"areaName": "嘉兴市,random"}
    )

    assert len(request.dimensions[0]) == len(PROVINCE_AREA_CODES) == 34
    assert {option[0][1] for option in request.dimensions[0]} == set(
        PROVINCE_AREA_CODES.values()
    )
    assert "330400" not in {option[0][1] for option in request.dimensions[0]}


def test_crawl_random_job_types_are_unique_native_types():
    request = crawl_request_from_params({"jobType": "random"})

    assert request.dimensions[0] == (
        (("jobType", "01"),),
        (("jobType", "02"),),
        (("jobType", "03"),),
    )


def test_crawl_random_month_pay_becomes_dimension_not_common_item():
    request = crawl_request_from_params({"monthPay": "random"})

    assert request.common_items == ()
    assert {option[0][1] for option in request.dimensions[0]} == set(
        MONTH_PAY_NATIVE_VALUES.values()
    )


def test_crawl_random_month_pay_dominates_explicit_value():
    request = crawl_request_from_params({"monthPay": "2K-5K,random"})

    assert request.common_items == ()
    assert len(request.dimensions[0]) == len(MONTH_PAY_NATIVE_VALUES)


def test_query_does_not_accept_random_as_filter_enum():
    with pytest.raises(InvalidFilter):
        Query.from_params({"areaName": "random"})


@pytest.mark.parametrize("name", ["publishDateFrom", "publishDateTo", "random"])
def test_crawl_rejects_local_only_parameters(name):
    with pytest.raises(ValueError, match="only supported by /query"):
        crawl_request_from_params({name: "true"})


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"offset": 0}, "offset must be between 1 and 50"),
        ({"offset": 51}, "offset must be between 1 and 50"),
        ({"limit": 101}, "limit must be between 1 and 100"),
    ],
)
def test_crawl_rejects_invalid_remote_pagination(params, message):
    with pytest.raises(ValueError, match=message):
        crawl_request_from_params(params)
