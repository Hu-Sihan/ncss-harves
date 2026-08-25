from __future__ import annotations

from contextlib import nullcontext
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
from typing import ContextManager, Iterable, Sequence

from .models import Job, Query, QueryResult


JOB_COLUMNS = (
    "job_id", "job_name", "company_id", "company_name", "area_code", "area_name",
    "publish_date", "update_date", "low_month_pay", "high_month_pay", "month_pay_text",
    "degree_code", "degree_name", "major", "head_count", "company_property", "company_scale",
    "job_type", "job_type_name", "industry_sectors", "category_code", "category_name",
    "recruit_type", "member_level", "key_units", "sources_name", "sources_type",
    "employment_type", "description", "source_url", "tags_json", "list_payload_json",
    "detail_payload_json", "first_seen_at", "detail_fetched_at",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Repository:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    def connect(self, *, readonly: bool = False) -> sqlite3.Connection:
        if readonly:
            connection = sqlite3.connect(f"file:{self.path.as_posix()}?mode=ro", uri=True, timeout=5)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        if readonly:
            connection.execute("PRAGMA query_only=ON")
        else:
            connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def initialize_schema(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path, timeout=5) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    job_name TEXT NOT NULL DEFAULT '',
                    company_id TEXT NOT NULL DEFAULT '',
                    company_name TEXT NOT NULL DEFAULT '',
                    area_code TEXT NOT NULL DEFAULT '',
                    area_name TEXT NOT NULL DEFAULT '',
                    publish_date TEXT NOT NULL DEFAULT '',
                    update_date TEXT NOT NULL DEFAULT '',
                    low_month_pay REAL,
                    high_month_pay REAL,
                    month_pay_text TEXT NOT NULL DEFAULT '',
                    degree_code TEXT NOT NULL DEFAULT '',
                    degree_name TEXT NOT NULL DEFAULT '',
                    major TEXT NOT NULL DEFAULT '',
                    head_count INTEGER,
                    company_property TEXT NOT NULL DEFAULT '',
                    company_scale TEXT NOT NULL DEFAULT '',
                    job_type TEXT NOT NULL DEFAULT '',
                    job_type_name TEXT NOT NULL DEFAULT '',
                    industry_sectors TEXT NOT NULL DEFAULT '',
                    category_code TEXT NOT NULL DEFAULT '',
                    category_name TEXT NOT NULL DEFAULT '',
                    recruit_type TEXT NOT NULL DEFAULT '',
                    member_level TEXT NOT NULL DEFAULT '',
                    key_units TEXT NOT NULL DEFAULT '',
                    sources_name TEXT NOT NULL DEFAULT '',
                    sources_type TEXT NOT NULL DEFAULT '',
                    employment_type TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    source_url TEXT NOT NULL DEFAULT '',
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    list_payload_json TEXT NOT NULL DEFAULT '{}',
                    detail_payload_json TEXT NOT NULL DEFAULT '{}',
                    first_seen_at TEXT NOT NULL DEFAULT '',
                    detail_fetched_at TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS job_industries (
                    job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
                    industry_name TEXT NOT NULL,
                    PRIMARY KEY (job_id, industry_name)
                );
                CREATE TABLE IF NOT EXISTS job_categories (
                    job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
                    category_name TEXT NOT NULL,
                    PRIMARY KEY (job_id, category_name)
                );
                CREATE TABLE IF NOT EXISTS job_tags (
                    job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
                    tag_name TEXT NOT NULL,
                    PRIMARY KEY (job_id, tag_name)
                );
                CREATE TABLE IF NOT EXISTS job_areas (
                    job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
                    area_name TEXT NOT NULL,
                    PRIMARY KEY (job_id, area_name)
                );
                CREATE TABLE IF NOT EXISTS runtime_state (
                    state_key TEXT PRIMARY KEY,
                    state_value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_name ON jobs(job_name);
                CREATE INDEX IF NOT EXISTS idx_jobs_area ON jobs(area_name);
                CREATE INDEX IF NOT EXISTS idx_jobs_degree ON jobs(degree_name);
                CREATE INDEX IF NOT EXISTS idx_jobs_type ON jobs(job_type_name);
                CREATE INDEX IF NOT EXISTS idx_jobs_category ON jobs(category_name);
                CREATE INDEX IF NOT EXISTS idx_jobs_property ON jobs(company_property);
                CREATE INDEX IF NOT EXISTS idx_jobs_publish_date ON jobs(publish_date);
                CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(sources_name);
                """
            )
            current = now_iso()
            connection.execute(
                "INSERT OR IGNORE INTO runtime_state VALUES ('schema_version', '1', ?)", (current,)
            )
            connection.execute(
                "INSERT OR IGNORE INTO runtime_state VALUES ('initialized', 'false', ?)", (current,)
            )

    def get_state(self, key: str, default: str = "") -> str:
        with self.connect(readonly=True) as connection:
            row = connection.execute(
                "SELECT state_value FROM runtime_state WHERE state_key = ?", (key,)
            ).fetchone()
        return str(row[0]) if row else default

    def is_initialized(self) -> bool:
        return self.get_state("initialized", "false").lower() == "true"

    @staticmethod
    def _set_state(connection: sqlite3.Connection, key: str, value: object) -> None:
        connection.execute(
            """INSERT INTO runtime_state(state_key, state_value, updated_at) VALUES (?, ?, ?)
               ON CONFLICT(state_key) DO UPDATE SET
                 state_value=excluded.state_value, updated_at=excluded.updated_at""",
            (key, str(value).lower() if isinstance(value, bool) else str(value), now_iso()),
        )

    def set_initialized(self, value: bool) -> None:
        with self.connect() as connection:
            self._set_state(connection, "initialized", value)
            if value:
                self._set_state(connection, "initialized_at", now_iso())

    def insert_batch(
        self,
        jobs: Sequence[Job],
        *,
        mark_initialized: bool = False,
        commit_guard: ContextManager[None] | None = None,
    ) -> int:
        guard = commit_guard or nullcontext()
        with guard, self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                inserted = 0
                for job in jobs:
                    rowcount = self._insert_job(connection, job)
                    if rowcount:
                        inserted += 1
                        self._insert_relations(connection, job)
                if mark_initialized:
                    self._set_state(connection, "initialized", True)
                    self._set_state(connection, "initialized_at", now_iso())
                connection.commit()
                return inserted
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _insert_job(connection: sqlite3.Connection, job: Job) -> int:
        values = asdict(job)
        current = now_iso()
        values["tags_json"] = json.dumps(values.pop("tags"), ensure_ascii=False)
        values["list_payload_json"] = json.dumps(values.pop("list_payload"), ensure_ascii=False)
        values["detail_payload_json"] = json.dumps(values.pop("detail_payload"), ensure_ascii=False)
        values["first_seen_at"] = values["first_seen_at"] or current
        values["detail_fetched_at"] = values["detail_fetched_at"] or current
        columns = ", ".join(JOB_COLUMNS)
        placeholders = ", ".join("?" for _ in JOB_COLUMNS)
        cursor = connection.execute(
            f"INSERT OR IGNORE INTO jobs ({columns}) VALUES ({placeholders})",
            tuple(values[column] for column in JOB_COLUMNS),
        )
        return max(0, int(cursor.rowcount))

    @staticmethod
    def _insert_relations(connection: sqlite3.Connection, job: Job) -> None:
        industries = tuple(
            dict.fromkeys(part.strip() for part in re.split(r"[,，、;/；|]", job.industry_sectors) if part.strip())
        )
        categories = (job.category_name,) if job.category_name else ()
        areas = (job.area_name,) if job.area_name else ()
        for table, column, values in (
            ("job_industries", "industry_name", industries),
            ("job_categories", "category_name", categories),
            ("job_tags", "tag_name", job.tags),
            ("job_areas", "area_name", areas),
        ):
            connection.executemany(
                f"INSERT OR IGNORE INTO {table}(job_id, {column}) VALUES (?, ?)",
                ((job.job_id, value) for value in values if value),
            )

    def count_all(self) -> int:
        with self.connect(readonly=True) as connection:
            return int(connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0])

    def detail_cache(self, job_ids: Iterable[str]) -> dict[str, Job]:
        unique = tuple(dict.fromkeys(str(job_id) for job_id in job_ids if str(job_id)))
        cached: dict[str, Job] = {}
        with self.connect(readonly=True) as connection:
            for start in range(0, len(unique), 500):
                chunk = unique[start : start + 500]
                if not chunk:
                    continue
                placeholders = ",".join("?" for _ in chunk)
                rows = connection.execute(
                    f"SELECT * FROM jobs WHERE job_id IN ({placeholders}) "
                    "AND description <> '' AND detail_fetched_at <> ''",
                    chunk,
                ).fetchall()
                for row in rows:
                    job = self._row_to_job(row)
                    cached[job.job_id] = job
        return cached

    def query(self, query: Query) -> QueryResult:
        clauses, params = self._where(query)
        where = " AND ".join(clauses) if clauses else "1=1"
        order = "RANDOM()" if query.random else "publish_date DESC, update_date DESC, job_id DESC"
        with self.connect(readonly=True) as connection:
            total = int(connection.execute(f"SELECT COUNT(*) FROM jobs WHERE {where}", params).fetchone()[0])
            rows = connection.execute(
                f"SELECT * FROM jobs WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
                (*params, query.limit, query.row_offset),
            ).fetchall()
        return QueryResult(tuple(self._row_to_job(row) for row in rows), total, query.page, query.limit)

    @staticmethod
    def _where(query: Query) -> tuple[list[str], list[object]]:
        clauses: list[str] = []
        params: list[object] = []

        def like(column: str, value: str) -> None:
            if value:
                clauses.append(f"{column} LIKE ?")
                params.append(f"%{value}%")

        def values_in(column: str, values: tuple[str, ...]) -> None:
            if values:
                placeholders = ",".join("?" for _ in values)
                clauses.append(f"{column} IN ({placeholders})")
                params.extend(values)

        def relation(table: str, column: str, values: tuple[str, ...]) -> None:
            if values:
                placeholders = ",".join("?" for _ in values)
                clauses.append(
                    f"EXISTS (SELECT 1 FROM {table} rel WHERE rel.job_id = jobs.job_id "
                    f"AND rel.{column} IN ({placeholders}))"
                )
                params.extend(values)

        like("job_name", query.job_name)
        like("month_pay_text", query.month_pay)
        if query.degree_names:
            degree_aliases = {
                "大专": ("大专", "专科"),
                "本科": ("本科",),
                "硕士": ("硕士",),
                "博士": ("博士",),
            }
            degree_values = tuple(
                alias for value in query.degree_names for alias in degree_aliases.get(value, (value,))
            )
            clauses.append("(" + " OR ".join("degree_name LIKE ?" for _ in degree_values) + ")")
            params.extend(f"%{value}%" for value in degree_values)
        if query.job_types:
            employment_values = tuple(
                {"全职": "full_time", "兼职": "part_time", "实习": "internship"}[value]
                for value in query.job_types
            )
            employment_placeholders = ",".join("?" for _ in employment_values)
            job_type_placeholders = ",".join("?" for _ in query.job_types)
            clauses.append(
                f"(employment_type IN ({employment_placeholders}) "
                f"OR job_type_name IN ({job_type_placeholders}))"
            )
            params.extend(employment_values)
            params.extend(query.job_types)
        values_in("company_property", query.properties)
        if query.area_names:
            clauses.append(
                "EXISTS (SELECT 1 FROM job_areas rel WHERE rel.job_id = jobs.job_id AND ("
                + " OR ".join("rel.area_name LIKE ?" for _ in query.area_names)
                + "))"
            )
            params.extend(f"%{value}%" for value in query.area_names)
        relation("job_categories", "category_name", query.category_names)
        relation("job_industries", "industry_name", query.industry_names)
        if query.recruit_types:
            recruit_values = tuple({"职位": "0", "公告": "1"}.get(value, value) for value in query.recruit_types)
            values_in("recruit_type", recruit_values)
        if query.company_types:
            company_clauses: list[str] = []
            if "重点领域" in query.company_types:
                company_clauses.append("key_units = '1'")
            if "精选企业" in query.company_types:
                company_clauses.append("member_level = '2'")
            clauses.append("(" + " OR ".join(company_clauses) + ")")
        if query.source_names:
            clauses.append("(" + " OR ".join("sources_name LIKE ?" for _ in query.source_names) + ")")
            params.extend(f"%{value}%" for value in query.source_names)
        if query.publish_date_from:
            clauses.append("publish_date >= ?")
            params.append(query.publish_date_from)
        if query.publish_date_to:
            clauses.append("publish_date <= ?")
            params.append(query.publish_date_to)
        return clauses, params

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> Job:
        values = dict(row)
        values["tags"] = tuple(json.loads(values.pop("tags_json") or "[]"))
        values["list_payload"] = json.loads(values.pop("list_payload_json") or "{}")
        values["detail_payload"] = json.loads(values.pop("detail_payload_json") or "{}")
        return Job(**values)
