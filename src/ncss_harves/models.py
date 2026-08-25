from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(slots=True)
class Job:
    job_id: str
    job_name: str = ""
    company_id: str = ""
    company_name: str = ""
    area_code: str = ""
    area_name: str = ""
    publish_date: str = ""
    update_date: str = ""
    low_month_pay: float | None = None
    high_month_pay: float | None = None
    month_pay_text: str = ""
    degree_code: str = ""
    degree_name: str = ""
    major: str = ""
    head_count: int | None = None
    company_property: str = ""
    company_scale: str = ""
    tags: tuple[str, ...] = ()
    job_type: str = ""
    job_type_name: str = ""
    industry_sectors: str = ""
    category_code: str = ""
    category_name: str = ""
    recruit_type: str = ""
    member_level: str = ""
    key_units: str = ""
    sources_name: str = ""
    sources_type: str = ""
    employment_type: str = ""
    description: str = ""
    source_url: str = ""
    list_payload: dict[str, Any] = field(default_factory=dict)
    detail_payload: dict[str, Any] = field(default_factory=dict)
    first_seen_at: str = ""
    detail_fetched_at: str = ""


@dataclass(frozen=True, slots=True)
class Query:
    job_name: str = ""
    area_names: tuple[str, ...] = ()
    degree_names: tuple[str, ...] = ()
    category_names: tuple[str, ...] = ()
    industry_names: tuple[str, ...] = ()
    job_types: tuple[str, ...] = ()
    properties: tuple[str, ...] = ()
    company_types: tuple[str, ...] = ()
    month_pay: str = ""
    recruit_types: tuple[str, ...] = ()
    source_names: tuple[str, ...] = ()
    publish_date_from: str = ""
    publish_date_to: str = ""
    random: bool = False
    page: int = 1
    limit: int = 20

    @classmethod
    def from_params(cls, params: Mapping[str, object]) -> "Query":
        from .filters import query_from_params

        return query_from_params(params)

    @property
    def row_offset(self) -> int:
        return (self.page - 1) * self.limit


@dataclass(frozen=True, slots=True)
class QueryResult:
    jobs: tuple[Job, ...]
    total: int
    page: int
    limit: int
