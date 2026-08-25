import pytest

from ncss_harves.errors import AuthenticationRequired, BlockedError, ResponseError
from ncss_harves.parsers import map_list_item, parse_detail_html, parse_list_payload


def test_login_required_shape_is_not_a_normal_empty_page():
    payload = {"flag": False, "data": None, "global": [{"des": "请登录后查看"}]}

    with pytest.raises(AuthenticationRequired, match="请登录后查看"):
        parse_list_payload(payload)


def test_list_payload_requires_object_data_and_list():
    with pytest.raises(ResponseError, match="data is not an object"):
        parse_list_payload({"flag": True, "data": []})
    with pytest.raises(ResponseError, match="job list is missing"):
        parse_list_payload({"flag": True, "data": {}})


def test_list_item_maps_native_fields_and_salary():
    job = map_list_item(
        {
            "jobId": "job-1",
            "jobName": "算法工程师",
            "recId": "company-1",
            "recName": "示例公司",
            "areaCode": "110000",
            "areaCodeName": "北京",
            "lowMonthPay": 15,
            "highMonthPay": 25,
            "degreeName": "本科",
            "jobType": "01",
            "categoryName": "计算机/网络/技术类",
            "industrySectors": "计算机软件",
            "sourcesName": "opaque-source-id",
            "sourcesNameCh": "智联招聘",
            "recTags": "五险一金,弹性工作",
        }
    )

    assert job.job_id == "job-1"
    assert job.company_id == "company-1"
    assert job.job_type_name == "全职"
    assert job.low_month_pay == 15000
    assert job.high_month_pay == 25000
    assert job.month_pay_text == "15000-25000元/月"
    assert job.tags == ("五险一金", "弹性工作")
    assert job.sources_name == "智联招聘"


def test_list_item_without_native_id_is_rejected():
    with pytest.raises(ResponseError, match="missing jobId"):
        map_list_item({"jobName": "无编号岗位"})


def test_detail_html_populates_description_and_industry():
    job = map_list_item({"jobId": "job-2", "jobName": "旧名称"})
    html = """
    <html><body>
      <h1 id="jobName">新名称</h1>
      <div id="industrySectors">计算机软件</div>
      <div class="jobdetail-box"><p>负责平台开发。</p><p>要求本科。</p></div>
      <div class="site-tag">浙江省杭州市</div>
      <span>实习</span>
    </body></html>
    """

    result = parse_detail_html(html, job)

    assert result.job_name == "新名称"
    assert result.industry_sectors == "计算机软件"
    assert "负责平台开发" in result.description
    assert result.employment_type == "internship"
    assert result.job_type == "03"
    assert result.job_type_name == "实习"
    assert result.area_name == "浙江省杭州市"
    assert result.detail_payload["html_fields"]["job_name"] == "新名称"


@pytest.mark.parametrize("marker", ["请登录后查看", "student/login.jsp"])
def test_detail_login_page_raises_authentication(marker):
    job = map_list_item({"jobId": "job-3"})
    with pytest.raises(AuthenticationRequired):
        parse_detail_html(f"<html>{marker}</html>", job)


def test_detail_verification_page_is_blocked():
    job = map_list_item({"jobId": "job-4"})
    with pytest.raises(BlockedError):
        parse_detail_html("<html>请完成人机验证</html>", job)
