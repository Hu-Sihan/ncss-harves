from pathlib import Path

import pytest

from ncss_harves.models import Job, Query
from ncss_harves.storage import Repository


def make_job(index: int, **changes) -> Job:
    values = {
        "job_id": f"job-{index}",
        "job_name": f"岗位 {index}",
        "company_id": f"company-{index}",
        "company_name": f"公司 {index}",
        "area_name": "北京" if index % 2 else "上海",
        "degree_name": "本科",
        "job_type_name": "实习" if index % 2 else "全职",
        "category_name": "计算机/网络/技术类",
        "industry_sectors": "计算机软件,互联网/电子商务",
        "company_property": "国有企业" if index == 1 else "民营企业",
        "key_units": "1" if index == 1 else "",
        "member_level": "2" if index == 2 else "",
        "recruit_type": "0",
        "sources_name": "国家大学生就业服务平台",
        "publish_date": f"2026-08-{index:02d}",
        "tags": ("五险一金", f"标签{index}"),
        "description": f"详情 {index}",
        "list_payload": {"jobId": f"job-{index}"},
        "detail_payload": {"html_fields": {"description": f"详情 {index}"}},
    }
    values.update(changes)
    return Job(**values)


@pytest.fixture
def repo(tmp_path: Path) -> Repository:
    repository = Repository(tmp_path / "ncss.db")
    repository.initialize_schema()
    return repository


def test_schema_starts_uninitialized_and_uses_wal(repo):
    assert repo.is_initialized() is False
    with repo.connect(readonly=True) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"jobs", "job_industries", "job_categories", "job_tags", "job_areas", "runtime_state"} <= tables


def test_batch_insert_is_atomic_and_sets_initialized(repo):
    jobs = [make_job(1), make_job(2)]

    inserted = repo.insert_batch(jobs, mark_initialized=True)

    assert inserted == 2
    assert repo.is_initialized() is True
    assert repo.count_all() == 2


def test_batch_rolls_back_jobs_relations_and_state_on_error(repo, monkeypatch):
    def fail_relations(*_args, **_kwargs):
        raise RuntimeError("relation failure")

    monkeypatch.setattr(repo, "_insert_relations", fail_relations)

    with pytest.raises(RuntimeError, match="relation failure"):
        repo.insert_batch([make_job(1)], mark_initialized=True)

    assert repo.count_all() == 0
    assert repo.is_initialized() is False


def test_duplicate_job_id_is_ignored_without_overwriting(repo):
    repo.insert_batch([make_job(1)])

    inserted = repo.insert_batch([make_job(1, job_name="被覆盖")])
    result = repo.query(Query.from_params({"offset": 1, "limit": 20}))

    assert inserted == 0
    assert result.jobs[0].job_name == "岗位 1"


def test_query_page_is_one_based_and_payloads_round_trip(repo):
    repo.insert_batch([make_job(index) for index in range(1, 6)])

    result = repo.query(Query.from_params({"offset": 2, "limit": 2}))

    assert result.page == 2
    assert result.limit == 2
    assert result.total == 5
    assert [job.job_id for job in result.jobs] == ["job-3", "job-2"]
    assert result.jobs[0].list_payload == {"jobId": "job-3"}
    assert result.jobs[0].detail_payload["html_fields"]["description"] == "详情 3"


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"areaName": "北京"}, {"job-1", "job-3"}),
        ({"jobType": "工作"}, {"job-2"}),
        ({"industrySectors": "计算机软件"}, {"job-1", "job-2", "job-3"}),
        ({"categoryName": "计算机/网络/技术类"}, {"job-1", "job-2", "job-3"}),
        ({"property": "国有企业"}, {"job-1"}),
        ({"companyType": "重点领域"}, {"job-1"}),
        ({"companyType": "精选企业"}, {"job-2"}),
        ({"sourceName": "国家大学生就业服务平台"}, {"job-1", "job-2", "job-3"}),
    ],
)
def test_query_filters_normalized_and_relation_fields(repo, params, expected):
    repo.insert_batch([make_job(1), make_job(2), make_job(3)])

    result = repo.query(Query.from_params(params))

    assert {job.job_id for job in result.jobs} == expected
    assert result.total == len(expected)


def test_detail_cache_returns_only_complete_requested_jobs(repo):
    repo.insert_batch([
        make_job(1, description="完整详情", detail_fetched_at="2026-08-25T00:00:00Z"),
        make_job(2, description="", detail_fetched_at="2026-08-25T00:00:00Z"),
        make_job(3, description="完整详情", detail_fetched_at="2026-08-25T00:00:00Z"),
    ])

    cached = repo.detail_cache(["job-1", "job-2", "job-4"])

    assert set(cached) == {"job-1"}
    assert cached["job-1"].description == "完整详情"


def test_query_uses_detail_employment_type_and_fuzzy_city(repo):
    repo.insert_batch([
        make_job(
            1,
            area_name="浙江省杭州市",
            job_type_name="",
            employment_type="internship",
            degree_name="本科及以上",
        )
    ])

    result = repo.query(Query.from_params({
        "areaName": "杭州市",
        "jobType": "实习",
        "degreeName": "本科",
    }))

    assert result.total == 1
    assert result.jobs[0].job_id == "job-1"
