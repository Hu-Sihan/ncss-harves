from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from html.parser import HTMLParser
import re
from typing import Any

from .errors import AuthenticationRequired, BlockedError, ResponseError
from .models import Job


DETAIL_URL = "https://www.ncss.cn/student/jobs/{job_id}/detail.html"


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return ",".join(_text(item) for item in value)
    return str(value).strip()


def _number(value: Any) -> float | None:
    if value in (None, "", "--"):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _salary(value: Any) -> float | None:
    number = _number(value)
    if number is None or number <= 0:
        return None
    return number * 1000 if number < 1000 else number


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _split(value: Any) -> tuple[str, ...]:
    values = value if isinstance(value, (list, tuple, set)) else re.split(r"[,，、;/；|]", _text(value))
    return tuple(dict.fromkeys(item for item in (_text(part) for part in values) if item))


def _date(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000
        return datetime.fromtimestamp(number, tz=timezone.utc).date().isoformat()
    return _text(value).replace("/", "-")[:10]


def map_list_item(payload: dict[str, Any]) -> Job:
    if not isinstance(payload, dict):
        raise ResponseError("job item is not an object")
    job_id = _text(payload.get("jobId") or payload.get("id"))
    if not job_id:
        raise ResponseError("missing jobId")
    low = _salary(payload.get("lowMonthPay"))
    high = _salary(payload.get("highMonthPay"))
    if low is None and high is None:
        salary_text = ""
    elif low is None:
        salary_text = f"最高{high:g}元/月"
    elif high is None or high == low:
        salary_text = f"{low:g}元/月"
    else:
        salary_text = f"{low:g}-{high:g}元/月"
    job_type = _text(payload.get("jobType"))
    job_type_name = {"01": "全职", "02": "兼职", "03": "实习"}.get(job_type, job_type)
    return Job(
        job_id=job_id,
        job_name=_text(payload.get("jobName")),
        company_id=_text(payload.get("recId") or payload.get("companyId")),
        company_name=_text(payload.get("recName") or payload.get("companyName")),
        area_code=_text(payload.get("areaCode")),
        area_name=_text(payload.get("areaCodeName") or payload.get("areaName")),
        publish_date=_date(payload.get("publishDate")),
        update_date=_date(payload.get("updateDate")),
        low_month_pay=low,
        high_month_pay=high,
        month_pay_text=salary_text,
        degree_code=_text(payload.get("degreeCode")),
        degree_name=_text(payload.get("degreeName")),
        major=_text(payload.get("major")),
        head_count=_integer(payload.get("headCount")),
        company_property=_text(payload.get("recProperty") or payload.get("companyProperty")),
        company_scale=_text(payload.get("recScale") or payload.get("companyScale")),
        tags=_split(payload.get("recTags") or payload.get("tags")),
        job_type=job_type,
        job_type_name=job_type_name,
        industry_sectors=_text(payload.get("industrySectors") or payload.get("industrySector")),
        category_code=_text(payload.get("categoryCode")),
        category_name=_text(payload.get("categoryName")),
        recruit_type=_text(payload.get("recruitType")),
        member_level=_text(payload.get("memberLevel")),
        key_units=_text(payload.get("keyUnits")),
        sources_name=_text(payload.get("sourcesNameCh") or payload.get("sourcesName")),
        sources_type=_text(payload.get("sourcesType")),
        employment_type={"全职": "full_time", "兼职": "part_time", "实习": "internship"}.get(job_type_name, ""),
        source_url=DETAIL_URL.format(job_id=job_id),
        list_payload=dict(payload),
    )


def parse_list_payload(payload: object) -> tuple[list[Job], dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ResponseError("payload is not an object")
    data = payload.get("data")
    global_messages = payload.get("global") or []
    if isinstance(global_messages, dict):
        global_messages = [global_messages]
    message = " ".join(
        _text(item.get("des") if isinstance(item, dict) else item) for item in global_messages
    )
    if payload.get("flag") is False and data is None and ("请登录" in message or "登录后查看" in message):
        raise AuthenticationRequired(message or "请登录后查看")
    if not isinstance(data, dict):
        raise ResponseError("data is not an object")
    items: object | None = None
    for key in ("list", "records", "rows", "items"):
        if key in data:
            items = data[key]
            break
    if items is None:
        raise ResponseError("job list is missing")
    if not isinstance(items, list):
        raise ResponseError("job list is not an array")
    return [map_list_item(item) for item in items], data


class _DetailParser(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.targets: list[tuple[str, int]] = []
        self.fragments: dict[str, list[str]] = {
            "description": [], "industry": [], "job_name": [], "area_name": []
        }
        self.employment_type = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.VOID:
            return
        self.depth += 1
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        element_id = attributes.get("id") or ""
        if "jobdetail-box" in classes:
            self.targets.append(("description", self.depth))
        if element_id == "industrySectors":
            self.targets.append(("industry", self.depth))
        if element_id == "jobName":
            self.targets.append(("job_name", self.depth))
        if "site-tag" in classes:
            self.targets.append(("area_name", self.depth))

    def handle_data(self, data: str) -> None:
        text = re.sub(r"\s+", " ", data).strip()
        if not text:
            return
        for target, _ in self.targets:
            self.fragments[target].append(text)
        if text in {"全职", "兼职", "实习", "实习生"}:
            self.employment_type = {
                "全职": "full_time", "兼职": "part_time", "实习": "internship", "实习生": "internship"
            }[text]

    def handle_endtag(self, tag: str) -> None:
        if tag in self.VOID:
            return
        self.targets = [target for target in self.targets if target[1] != self.depth]
        self.depth = max(0, self.depth - 1)


def parse_detail_html(html: str, job: Job) -> Job:
    if not isinstance(html, str) or not html.strip():
        raise ResponseError("empty detail html")
    if any(marker in html for marker in ("请登录后查看", "student/login.jsp", "passport/login")):
        raise AuthenticationRequired("NCSS detail requires login")
    if any(marker in html for marker in ("安全验证", "验证码", "人机验证", "访问受限", "频繁访问")):
        raise BlockedError("NCSS detail page is blocked")
    parser = _DetailParser()
    parser.feed(html)
    parser.close()
    fields = {
        "description": "\n".join(parser.fragments["description"]).strip(),
        "industry": " ".join(parser.fragments["industry"]).strip().strip("--"),
        "job_name": " ".join(parser.fragments["job_name"]).strip(),
        "area_name": " ".join(parser.fragments["area_name"]).strip(),
        "employment_type": parser.employment_type,
    }
    if not fields["description"] and not fields["industry"] and not fields["job_name"]:
        raise ResponseError("invalid detail page structure")
    detail_payload = dict(job.detail_payload)
    detail_payload["html_fields"] = fields
    employment_type = fields["employment_type"] or job.employment_type
    job_type, job_type_name = {
        "full_time": ("01", "全职"),
        "part_time": ("02", "兼职"),
        "internship": ("03", "实习"),
    }.get(employment_type, (job.job_type, job.job_type_name))
    return replace(
        job,
        job_name=fields["job_name"] or job.job_name,
        area_name=fields["area_name"] or job.area_name,
        industry_sectors=fields["industry"] or job.industry_sectors,
        job_type=job_type,
        job_type_name=job_type_name,
        employment_type=employment_type,
        description=fields["description"] or job.description,
        detail_payload=detail_payload,
    )
