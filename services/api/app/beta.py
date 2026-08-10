from __future__ import annotations

from datetime import UTC, datetime
from difflib import SequenceMatcher
from sqlite3 import Connection
from statistics import median
from typing import Literal, TypedDict
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.database import Database
from app.models import Genre
from app.repository import NotFoundError

BetaFeedbackCategory = Literal[
    "workflow",
    "ai_quality",
    "reliability",
    "originality",
    "usability",
]
BetaFeedbackContext = Literal[
    "writing",
    "director",
    "review",
    "reference",
    "recovery",
    "release",
]
BetaEventType = Literal[
    "manuscript_export",
    "project_export",
    "recovery_restore",
    "report_export",
]


class BetaTemplate(BaseModel):
    id: str
    label: str
    genre: Genre
    suggested_title: str
    rebirth_year: int
    rebirth_location: str
    idea_prompt: str
    reality_anchor: str
    first_ten_chapter_goal: str


class CreateBetaFeedbackRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    category: BetaFeedbackCategory
    context: BetaFeedbackContext
    rating: int = Field(ge=1, le=5)
    note: str = Field(default="", max_length=2000)

    @field_validator("note")
    @classmethod
    def reject_null_bytes(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("反馈不能包含空字节")
        return value


class BetaFeedback(BaseModel):
    id: str
    project_id: str
    category: BetaFeedbackCategory
    context: BetaFeedbackContext
    rating: int
    note: str
    created_at: str


class BetaMilestone(BaseModel):
    key: str
    label: str
    completed: bool
    evidence_count: int = Field(ge=0)


class BetaMetrics(BaseModel):
    chapter_count: int = Field(ge=0)
    written_chapter_count: int = Field(ge=0)
    approved_chapter_count: int = Field(ge=0)
    ai_candidate_count: int = Field(ge=0)
    ai_applied_count: int = Field(ge=0)
    ai_adoption_rate: float | None
    mean_manual_modification_ratio: float | None
    review_finding_count: int = Field(ge=0)
    review_accepted_count: int = Field(ge=0)
    review_acceptance_rate: float | None
    median_seconds_to_approved_chapter: float | None
    estimated_cost_microusd: int = Field(ge=0)
    failed_or_interrupted_jobs: int = Field(ge=0)
    recovered_retry_jobs: int = Field(ge=0)
    retry_recovery_rate: float | None
    open_critical_findings: int = Field(ge=0)
    originality_blocked_count: int = Field(ge=0)


class BetaEvaluationReport(BaseModel):
    format: Literal["mozhou-closed-beta-report"] = "mozhou-closed-beta-report"
    format_version: Literal[1] = 1
    generated_at: str
    project_id: str
    template_ids: list[str]
    milestones: list[BetaMilestone]
    metrics: BetaMetrics
    feedback: list[BetaFeedback]
    privacy_notice: str


BETA_TEMPLATES = [
    BetaTemplate(
        id="historical-rebirth",
        label="历史重生 · 山河改写",
        genre=Genre.HISTORICAL_REBIRTH,
        suggested_title="烽火归途",
        rebirth_year=1937,
        rebirth_location="福建南平",
        idea_prompt="一个熟知后世转折的人回到危局前夜，先救下身边人，再改变一条关键因果链。",
        reality_anchor="地方地理、交通、组织能力和当年制度必须有来源；未来知识会随分歧失效。",
        first_ten_chapter_goal="建立生存压力、可信资源和第一个不可逆分歧，并兑现一次小胜。",
    ),
    BetaTemplate(
        id="urban-rebirth",
        label="都市重生 · 小城商路",
        genre=Genre.URBAN_REBIRTH,
        suggested_title="回到九八年的南平",
        rebirth_year=1998,
        rebirth_location="福建南平",
        idea_prompt="主角回到家庭与事业同时转折的一年，从一笔小订单开始重新积累信用和资源。",
        reality_anchor="年代物件、工资物价、产业链和城市生活需匹配 1998 年现实条件。",
        first_ten_chapter_goal="保住家庭底线、完成首单闭环、建立竞争者，并留下更大行业机会。",
    ),
    BetaTemplate(
        id="reality-anchor",
        label="现实锚点 · 地方产业",
        genre=Genre.URBAN_REBIRTH,
        suggested_title="闽北新局",
        rebirth_year=2008,
        rebirth_location="福建南平",
        idea_prompt="主角以地方产业和真实组织为边界，在已知经济周期前寻找一条可落地的新路径。",
        reality_anchor="先导入公开统计、地方志、交通和产业资料，确认后才进入创作上下文。",
        first_ten_chapter_goal="完成调研、建立利益关系、验证最小商业闭环，并暴露扩张代价。",
    ),
]


class BetaCounts(TypedDict):
    genre: str
    chapters: int
    written_chapters: int
    approved_chapters: int
    ai_candidates: int
    ai_applied: int
    review_findings: int
    review_accepted: int
    critical_findings: int
    estimated_cost_microusd: int
    failed_jobs: int
    recovered_jobs: int
    originality_blocked: int
    blueprints: int
    fact_applied: int
    reference_applied: int
    recovery_points: int
    exports: int


class BetaEvaluationService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list_templates(self) -> list[BetaTemplate]:
        return BETA_TEMPLATES

    def create_feedback(
        self,
        project_id: str,
        request: CreateBetaFeedbackRequest,
    ) -> BetaFeedback:
        feedback_id = str(uuid4())
        created_at = datetime.now(UTC).isoformat()
        with self.database.connect() as connection:
            if connection.execute(
                "SELECT 1 FROM projects WHERE id = ?", (project_id,)
            ).fetchone() is None:
                raise NotFoundError(project_id)
            connection.execute(
                """
                INSERT INTO beta_feedback (
                    id, project_id, category, context, rating, note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    feedback_id,
                    project_id,
                    request.category,
                    request.context,
                    request.rating,
                    request.note,
                    created_at,
                ),
            )
        return BetaFeedback(
            id=feedback_id,
            project_id=project_id,
            category=request.category,
            context=request.context,
            rating=request.rating,
            note=request.note,
            created_at=created_at,
        )

    def record_event(self, project_id: str, event_type: BetaEventType) -> None:
        with self.database.connect() as connection:
            if connection.execute(
                "SELECT 1 FROM projects WHERE id = ?", (project_id,)
            ).fetchone() is None:
                raise NotFoundError(project_id)
            connection.execute(
                "INSERT INTO beta_events (id, project_id, event_type, created_at) VALUES (?, ?, ?, ?)",
                (str(uuid4()), project_id, event_type, datetime.now(UTC).isoformat()),
            )

    def report(self, project_id: str) -> BetaEvaluationReport:
        with self.database.connect() as connection:
            if connection.execute(
                "SELECT 1 FROM projects WHERE id = ?", (project_id,)
            ).fetchone() is None:
                raise NotFoundError(project_id)
            counts = self._counts(connection, project_id)
            feedback = [
                BetaFeedback.model_validate(dict(row))
                for row in connection.execute(
                    "SELECT * FROM beta_feedback WHERE project_id = ? ORDER BY created_at, id",
                    (project_id,),
                ).fetchall()
            ]
            modification_ratios = self._manual_modification_ratios(connection, project_id)
            approval_seconds = self._approval_seconds(connection, project_id)

        metrics = BetaMetrics(
            chapter_count=counts["chapters"],
            written_chapter_count=counts["written_chapters"],
            approved_chapter_count=counts["approved_chapters"],
            ai_candidate_count=counts["ai_candidates"],
            ai_applied_count=counts["ai_applied"],
            ai_adoption_rate=self._rate(counts["ai_applied"], counts["ai_candidates"]),
            mean_manual_modification_ratio=(
                round(sum(modification_ratios) / len(modification_ratios), 4)
                if modification_ratios
                else None
            ),
            review_finding_count=counts["review_findings"],
            review_accepted_count=counts["review_accepted"],
            review_acceptance_rate=self._rate(
                counts["review_accepted"], counts["review_findings"]
            ),
            median_seconds_to_approved_chapter=(
                round(median(approval_seconds), 3) if approval_seconds else None
            ),
            estimated_cost_microusd=counts["estimated_cost_microusd"],
            failed_or_interrupted_jobs=counts["failed_jobs"],
            recovered_retry_jobs=counts["recovered_jobs"],
            retry_recovery_rate=self._rate(counts["recovered_jobs"], counts["failed_jobs"]),
            open_critical_findings=counts["critical_findings"],
            originality_blocked_count=counts["originality_blocked"],
        )
        milestones = self._milestones(counts)
        matching_templates = [
            template.id
            for template in BETA_TEMPLATES
            if template.genre.value == counts["genre"]
        ]
        return BetaEvaluationReport(
            generated_at=datetime.now(UTC).isoformat(),
            project_id=project_id,
            template_ids=matching_templates,
            milestones=milestones,
            metrics=metrics,
            feedback=feedback,
            privacy_notice=(
                "报告不含作品名、正文、章纲、资料原文、Prompt、文件路径或密钥；"
                "仅包含流程计数、比例、费用估算和作者主动填写的反馈。"
            ),
        )

    @staticmethod
    def _rate(numerator: int, denominator: int) -> float | None:
        return round(numerator / denominator, 4) if denominator > 0 else None

    @staticmethod
    def _scalar(
        connection: Connection,
        query: str,
        parameters: tuple[str, ...],
    ) -> int:
        row = connection.execute(query, parameters).fetchone()
        return int(row[0]) if row is not None else 0

    def _counts(self, connection: Connection, project_id: str) -> BetaCounts:
        scalar = lambda query: self._scalar(connection, query, (project_id,))
        genre_row = connection.execute(
            "SELECT genre FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        return {
            "genre": str(genre_row[0]),
            "chapters": scalar(
                "SELECT COUNT(*) FROM chapters "
                "WHERE project_id = ? AND deleted_at IS NULL"
            ),
            "written_chapters": scalar(
                "SELECT COUNT(*) FROM chapters WHERE project_id = ? "
                "AND deleted_at IS NULL AND LENGTH(TRIM(content)) > 0"
            ),
            "approved_chapters": scalar(
                "SELECT COUNT(*) FROM chapters WHERE project_id = ? "
                "AND deleted_at IS NULL AND status = 'approved'"
            ),
            "ai_candidates": scalar(
                "SELECT COUNT(*) FROM chapter_versions v JOIN chapters c ON c.id = v.chapter_id "
                "WHERE c.project_id = ? AND v.source = 'generation_candidate'"
            ),
            "ai_applied": scalar(
                "SELECT COUNT(*) FROM chapter_versions v JOIN chapters c ON c.id = v.chapter_id "
                "WHERE c.project_id = ? AND v.source = 'generation_apply'"
            ),
            "review_findings": scalar(
                "SELECT COUNT(*) FROM review_findings WHERE project_id = ?"
            ),
            "review_accepted": scalar(
                "SELECT COUNT(*) FROM review_findings WHERE project_id = ? "
                "AND state IN ('accepted', 'resolved')"
            ),
            "critical_findings": scalar(
                "SELECT COUNT(*) FROM review_findings WHERE project_id = ? "
                "AND severity = 'critical' AND state = 'open'"
            ),
            "estimated_cost_microusd": scalar(
                "SELECT COALESCE(SUM(a.estimated_cost_microusd), 0) FROM job_attempts a "
                "JOIN jobs j ON j.id = a.job_id WHERE j.project_id = ?"
            ),
            "failed_jobs": scalar(
                "SELECT COUNT(*) FROM jobs WHERE project_id = ? AND state IN ('failed', 'interrupted')"
            ),
            "recovered_jobs": scalar(
                "SELECT COUNT(*) FROM jobs WHERE project_id = ? AND parent_job_id IS NOT NULL AND state = 'succeeded'"
            ),
            "originality_blocked": scalar(
                "SELECT COUNT(*) FROM reference_pattern_applications "
                "WHERE project_id = ? AND originality_status = 'blocked'"
            ),
            "blueprints": scalar("SELECT COUNT(*) FROM book_blueprints WHERE project_id = ?"),
            "fact_applied": scalar(
                "SELECT COUNT(*) FROM fact_change_sets f JOIN chapters c ON c.id = f.chapter_id "
                "WHERE c.project_id = ? AND f.state = 'applied'"
            ),
            "reference_applied": scalar(
                "SELECT COUNT(*) FROM reference_pattern_applications "
                "WHERE project_id = ? AND originality_status = 'passed'"
            ),
            "recovery_points": scalar(
                "SELECT COUNT(*) FROM project_recovery_points WHERE project_id = ?"
            ),
            "exports": scalar(
                "SELECT COUNT(*) FROM beta_events WHERE project_id = ? "
                "AND event_type IN ('manuscript_export', 'project_export')"
            ),
        }

    @staticmethod
    def _manual_modification_ratios(
        connection: Connection,
        project_id: str,
    ) -> list[float]:
        rows = connection.execute(
            """
            SELECT c.content AS current_content, v.content AS applied_content
            FROM chapters c
            JOIN chapter_versions v ON v.chapter_id = c.id
            WHERE c.project_id = ? AND v.source = 'generation_apply'
              AND v.version_number = (
                SELECT MAX(v2.version_number) FROM chapter_versions v2
                WHERE v2.chapter_id = c.id AND v2.source = 'generation_apply'
              )
            """,
            (project_id,),
        ).fetchall()
        return [
            1 - SequenceMatcher(
                None,
                str(row["applied_content"]),
                str(row["current_content"]),
                autojunk=False,
            ).ratio()
            for row in rows
        ]

    @staticmethod
    def _approval_seconds(connection: Connection, project_id: str) -> list[float]:
        rows = connection.execute(
            """
            SELECT MIN(v.created_at) AS started_at, MIN(e.created_at) AS approved_at
            FROM chapters c
            JOIN chapter_versions v ON v.chapter_id = c.id AND v.is_candidate = 0
            JOIN chapter_events e ON e.chapter_id = c.id AND e.to_status = 'approved'
            WHERE c.project_id = ?
            GROUP BY c.id
            """,
            (project_id,),
        ).fetchall()
        durations: list[float] = []
        for row in rows:
            started_at = datetime.fromisoformat(str(row["started_at"]))
            approved_at = datetime.fromisoformat(str(row["approved_at"]))
            durations.append(max(0.0, (approved_at - started_at).total_seconds()))
        return durations

    @staticmethod
    def _milestones(counts: BetaCounts) -> list[BetaMilestone]:
        definitions = [
            ("project", "建立或导入作品", 1, 1),
            ("plan", "形成整书蓝图与滚动计划", counts["blueprints"], 1),
            ("ten_chapters", "连续完成至少十章正文", counts["written_chapters"], 10),
            ("ai_candidate", "生成 AI 单章候选稿", counts["ai_candidates"], 1),
            ("ai_apply", "作者确认采用过候选稿", counts["ai_applied"], 1),
            ("review", "完成证据化审校", counts["review_findings"], 1),
            ("fact", "确认候选事实回灌", counts["fact_applied"], 1),
            ("reference", "应用通过原创性门禁的拆书蓝图", counts["reference_applied"], 1),
            ("recovery", "创建恢复点", counts["recovery_points"], 1),
            ("export", "导出正文或项目归档", counts["exports"], 1),
        ]
        return [
            BetaMilestone(
                key=key,
                label=label,
                completed=count >= target,
                evidence_count=count,
            )
            for key, label, count, target in definitions
        ]
