def test_package_version_is_exposed():
    import ncss_harves

    assert ncss_harves.__version__ == "0.2.0"
