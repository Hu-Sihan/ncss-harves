from ncss_harves.areas import AREA_CODES, AREA_TREE, PROVINCE_AREA_CODES


def test_area_catalog_matches_ncss_selector_scope():
    assert len(AREA_TREE) == 34
    assert sum(len(children) for _, _, children in AREA_TREE) == 357
    assert len(AREA_CODES) == 391
    assert len(set(AREA_CODES)) == 391
    assert len(set(AREA_CODES.values())) == 391


def test_province_area_catalog_contains_only_tree_roots():
    expected = {name: code for name, code, _ in AREA_TREE}

    assert PROVINCE_AREA_CODES == expected
    assert len(PROVINCE_AREA_CODES) == 34
    assert all(len(code) == 2 for code in PROVINCE_AREA_CODES.values())


def test_area_catalog_uses_official_names_and_native_codes():
    assert AREA_CODES["吉林"] == "22"
    assert AREA_CODES["吉林市"] == "220200"
    assert AREA_CODES["温州市"] == "330300"
    assert AREA_CODES["雄安新区"] == "133100"


def test_area_catalog_excludes_grouping_nodes_and_short_city_aliases():
    excluded = {
        "河南省直管县级行政区",
        "湖北省直管县级行政区",
        "海南省直管县级行政区",
        "县",
        "杭州",
        "温州",
        "长春",
    }
    assert excluded.isdisjoint(AREA_CODES)
