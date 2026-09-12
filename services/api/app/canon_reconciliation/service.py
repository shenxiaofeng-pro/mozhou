from __future__ import annotations

from sqlite3 import Row
from typing import cast

from pydantic import BaseModel, ConfigDict, Field

from app.context import (
    CreativeContextBlockedError,
    CreativeContextCompileRequest,
    CreativeContextPurpose,
    CreativeContextService,
    CreativeContextSubject,
    CreativeContextSubjectKind,
)
from app.jobs.models import Job
from app.jobs.repository import JobRepository
from app.jobs.runtime import JobExecutionContext, JobExecutionError
from app.models import ChapterStatus, DirectorSceneBeat, RollingChapterPlanContent
from app.repository import ProjectRepository

from .extractor import (
    extract_canon_candidates,
    extract_preference_candidates,
    text_sha256,
)
from .models import (
    AuthorPreferenceCandidateDraft,
    AuthorPreferenceDimension,
    CanonConflict,
    CanonConflictKind,
    CanonDecisionBatchRequest,
    CanonDecisionBatchResult,
    CanonDeltaCandidateDraft,
    CanonEvidence,
    CanonKind,
    MetricValue,
    PreferenceScopeKind,
    ReconciliationAnalysis,
    RollingPlanReplenishmentDraft,
)
from .repository import (
    CANON_RECONCILIATION_WORKFLOW,
    CanonReconciliationConflictError,
    CanonReconciliationNotFoundError,
    CanonReconciliationRepository,
    CanonReconciliationSourceChangedError,
    canonical_sha256,
)


class _ReconciliationJobInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, ge=1, le=1)
    approval_id: str = Field(min_length=1, max_length=200)
    chapter_version_id: str = Field(min_length=1, max_length=200)
    chapter_revision: int = Field(gt=0)
    chapter_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CanonReconciliationService:
    """Materialise author-gated Canon and preference candidates from one frozen approval."""

    def __init__(
        self,
        projects: ProjectRepository,
        reconciliations: CanonReconciliationRepository,
        jobs: JobRepository,
        creative_context: CreativeContextService,
    ) -> None:
        self.projects = projects
        self.reconciliations = reconciliations
        self.jobs = jobs
        self.creative_context = creative_context

    @staticmethod
    def handles(job: Job) -> bool:
        return job.workflow == CANON_RECONCILIATION_WORKFLOW

    def handle(self, context: JobExecutionContext, job: Job) -> None:
        if not self.handles(job):
            raise JobExecutionError("unsupported_workflow", "定稿整理任务类型不受支持")
        try:
            task = _ReconciliationJobInput.model_validate(self.jobs.load_input(job.id))
            reconciliation = self.reconciliations.get_reconciliation_by_job(job.id)
            approval = self.reconciliations.get_approval(task.approval_id)
            if (
                reconciliation.approval_id != approval.id
                or approval.project_id != job.project_id
                or approval.chapter_id != job.chapter_id
                or approval.chapter_version_id != task.chapter_version_id
                or approval.chapter_revision != task.chapter_revision
                or approval.chapter_content_sha256 != task.chapter_content_sha256
            ):
                self.reconciliations.mark_stale(
                    reconciliation.id,
                    "approval_snapshot_mismatch",
                )
                raise JobExecutionError("approval_changed", "定稿快照已变化，请重新打开章节")

            approved_body = self._approved_body(approval.chapter_version_id)
            if text_sha256(approved_body) != approval.chapter_content_sha256:
                self.reconciliations.mark_stale(
                    reconciliation.id,
                    "approval_content_hash_mismatch",
                )
                raise JobExecutionError("approval_changed", "定稿正文指纹无效")

            workspace = self.projects.get_workspace(approval.project_id)
            chapter = next(
                (item for item in workspace.chapters if item.id == approval.chapter_id),
                None,
            )
            if (
                chapter is None
                or chapter.status != ChapterStatus.APPROVED
                or chapter.revision != approval.chapter_revision
                or text_sha256(chapter.content) != approval.chapter_content_sha256
            ):
                self.reconciliations.mark_stale(
                    reconciliation.id,
                    "chapter_moved_after_approval",
                )
                raise JobExecutionError("chapter_changed", "章节已在定稿后变化，本次回流已隔离")

            context.checkpoint()
            self.jobs.update_progress(job.id, current=0, total=1, step="正在整理定稿事实")
            packet = self.creative_context.compile(
                workspace,
                CreativeContextCompileRequest(
                    purpose=CreativeContextPurpose.CANON_RECONCILIATION,
                    subject=CreativeContextSubject(
                        kind=CreativeContextSubjectKind.CHAPTER,
                        id=chapter.id,
                        revision=chapter.revision,
                        content_sha256=None,
                    ),
                    token_budget=24_000,
                    window_size=1,
                ),
            )
            self.creative_context.require_usable(packet)
            canon_candidates = self._canon_candidates(
                project_id=approval.project_id,
                chapter_id=approval.chapter_id,
                chapter_revision=approval.chapter_revision,
                approval_version_id=approval.chapter_version_id,
                approved_body=approved_body,
                approved_sha256=approval.chapter_content_sha256,
                default_event_year=workspace.project.rebirth_year,
            )
            preferences, skip_reason = self._preference_candidates(
                approval_id=approval.id,
                source_writing_outcome_id=approval.source_writing_outcome_id,
                project_id=approval.project_id,
                final_body=approved_body,
                final_sha256=approval.chapter_content_sha256,
            )
            context.checkpoint()
            self._require_current_approval(
                chapter_id=approval.chapter_id,
                chapter_revision=approval.chapter_revision,
                content_sha256=approval.chapter_content_sha256,
                reconciliation_id=reconciliation.id,
            )
            self.reconciliations.persist_analysis(
                reconciliation.id,
                ReconciliationAnalysis(
                    context_packet_id=packet.id,
                    context_packet_sha256=packet.packet_sha256,
                    context_dependency_fingerprint_sha256=(
                        packet.dependency_fingerprint_sha256
                    ),
                    canon_candidates=canon_candidates,
                    preference_candidates=preferences,
                    preference_skip_reason=skip_reason,
                ),
            )
            self.jobs.update_progress(job.id, current=1, total=1, step="定稿候选已整理")
        except JobExecutionError:
            raise
        except CreativeContextBlockedError as error:
            self._mark_failed(job, str(error))
            raise JobExecutionError("context_blocked", "定稿上下文未通过安全检查") from error
        except (CanonReconciliationConflictError, ValueError) as error:
            self._mark_failed(job, str(error))
            raise JobExecutionError("invalid_reconciliation", "定稿候选整理失败，可重试") from error

    def decide_batch(
        self,
        *,
        project_id: str,
        request: CanonDecisionBatchRequest,
    ) -> CanonDecisionBatchResult:
        """Apply author decisions and idempotently prepare the next planning buffer."""

        try:
            result = self.reconciliations.decide_batch(
                project_id=project_id,
                request=request,
            )
        except CanonReconciliationSourceChangedError:
            self.reconciliations.mark_stale(
                request.reconciliation_id,
                "chapter_changed_after_reconciliation",
            )
            raise
        reconciliation = self.reconciliations.get_reconciliation(
            request.reconciliation_id
        )
        if reconciliation.state.value != "decided":
            return result
        accepted_record_ids = self.reconciliations.list_accepted_canon_record_ids(
            project_id=project_id,
            reconciliation_id=reconciliation.id,
        )
        if not accepted_record_ids:
            return result
        snapshot = self.reconciliations.get_latest_snapshot(
            project_id=project_id,
            chapter_id=reconciliation.chapter_id,
        )
        if snapshot.rolling_plan_replenishment is not None:
            return result.model_copy(
                update={
                    "rolling_plan_replenishment_id": (
                        snapshot.rolling_plan_replenishment.id
                    )
                }
            )
        draft = self._rolling_plan_draft(
            project_id=project_id,
            reconciliation_id=reconciliation.id,
            source_chapter_id=reconciliation.chapter_id,
            source_decision_batch_id=result.batch_id,
            source_canon_record_ids=accepted_record_ids,
        )
        replenishment = self.reconciliations.create_rolling_plan_replenishment(
            project_id=project_id,
            reconciliation_id=reconciliation.id,
            draft=draft,
        )
        return result.model_copy(
            update={"rolling_plan_replenishment_id": replenishment.id}
        )

    def _mark_failed(self, job: Job, message: str) -> None:
        try:
            reconciliation = self.reconciliations.get_reconciliation_by_job(job.id)
            self.reconciliations.mark_failed(reconciliation.id, message)
        except (CanonReconciliationNotFoundError, CanonReconciliationConflictError):
            pass

    def _require_current_approval(
        self,
        *,
        chapter_id: str,
        chapter_revision: int,
        content_sha256: str,
        reconciliation_id: str,
    ) -> None:
        with self.reconciliations.database.connect() as connection:
            row = connection.execute(
                "SELECT status, revision, content FROM chapters WHERE id = ?",
                (chapter_id,),
            ).fetchone()
        if (
            row is None
            or row["status"] != ChapterStatus.APPROVED.value
            or int(row["revision"]) != chapter_revision
            or text_sha256(str(row["content"])) != content_sha256
        ):
            self.reconciliations.mark_stale(
                reconciliation_id,
                "chapter_moved_during_reconciliation",
            )
            raise JobExecutionError(
                "chapter_changed",
                "章节已在整理期间变化，本次回流已隔离",
            )

    def _rolling_plan_draft(
        self,
        *,
        project_id: str,
        reconciliation_id: str,
        source_chapter_id: str,
        source_decision_batch_id: str,
        source_canon_record_ids: list[str],
    ) -> RollingPlanReplenishmentDraft:
        workspace = self.projects.get_workspace(project_id)
        source = next(
            (chapter for chapter in workspace.chapters if chapter.id == source_chapter_id),
            None,
        )
        if source is None:
            raise CanonReconciliationNotFoundError(source_chapter_id)
        protected_numbers = sorted(
            {
                chapter.chapter_number
                for chapter in workspace.chapters
                if chapter.chapter_number > source.chapter_number
            }
            | {
                plan.chapter_number
                for plan in workspace.rolling_chapter_plans
                if plan.chapter_number > source.chapter_number
            }
        )
        future_count = len(protected_numbers)
        volume_plan = next(
            (
                plan
                for plan in workspace.volume_plans
                if plan.volume_number == source.volume_number
            ),
            workspace.volume_plans[0] if workspace.volume_plans else None,
        )
        blueprint = workspace.book_blueprint
        volume_plan_id = volume_plan.id if volume_plan is not None else None
        base_blueprint_id = blueprint.id if blueprint is not None else None
        base_blueprint_revision = blueprint.revision if blueprint is not None else None
        base_blueprint_content_sha256 = (
            canonical_sha256(blueprint.content.model_dump(mode="json"))
            if blueprint is not None
            else None
        )
        if future_count >= 3:
            return RollingPlanReplenishmentDraft(
                source_decision_batch_id=source_decision_batch_id,
                source_chapter_id=source_chapter_id,
                source_canon_record_ids=source_canon_record_ids,
                volume_plan_id=volume_plan_id,
                base_blueprint_id=base_blueprint_id,
                base_blueprint_revision=base_blueprint_revision,
                base_blueprint_content_sha256=base_blueprint_content_sha256,
                protected_chapter_numbers=protected_numbers,
                plans=[],
                blocked_reason="rolling_buffer_already_has_three_chapters",
            )
        if volume_plan is None:
            return RollingPlanReplenishmentDraft(
                source_decision_batch_id=source_decision_batch_id,
                source_chapter_id=source_chapter_id,
                source_canon_record_ids=source_canon_record_ids,
                volume_plan_id=volume_plan_id,
                base_blueprint_id=base_blueprint_id,
                base_blueprint_revision=base_blueprint_revision,
                base_blueprint_content_sha256=base_blueprint_content_sha256,
                protected_chapter_numbers=protected_numbers,
                plans=[],
                blocked_reason="volume_plan_required",
            )

        number_needed = 5 - future_count
        start_number = max(
            [source.chapter_number, *protected_numbers],
        ) + 1
        records = {
            record.id: record
            for record in self.reconciliations.list_canon_records(project_id)
        }
        accepted_summaries = [
            self._compact_canon_summary(records[record_id])
            for record_id in source_canon_record_ids
            if record_id in records
        ]
        canon_anchor = "；".join(accepted_summaries[:3]) or source.state_change
        plans = [
            self._next_chapter_plan(
                chapter_number=start_number + offset,
                source_title=source.title,
                canon_anchor=canon_anchor,
                volume_direction=volume_plan.direction,
                ordinal=offset + 1,
            )
            for offset in range(number_needed)
        ]
        return RollingPlanReplenishmentDraft(
            source_decision_batch_id=source_decision_batch_id,
            source_chapter_id=source_chapter_id,
            source_canon_record_ids=source_canon_record_ids,
            volume_plan_id=volume_plan_id,
            base_blueprint_id=base_blueprint_id,
            base_blueprint_revision=base_blueprint_revision,
            base_blueprint_content_sha256=base_blueprint_content_sha256,
            protected_chapter_numbers=protected_numbers,
            plans=plans,
            blocked_reason=None,
        )

    @staticmethod
    def _compact_canon_summary(record: object) -> str:
        summary = getattr(record, "subject_key", "新事实")
        payload = getattr(record, "payload", None)
        if payload is None:
            return str(summary)[:120]
        values = payload.model_dump(mode="json")
        detail = next(
            (
                str(values[key])
                for key in ("change", "state", "summary", "knowledge", "rank", "title")
                if values.get(key)
            ),
            "",
        )
        return f"{summary}：{detail}"[:160]

    @staticmethod
    def _next_chapter_plan(
        *,
        chapter_number: int,
        source_title: str,
        canon_anchor: str,
        volume_direction: str,
        ordinal: int,
    ) -> RollingChapterPlanContent:
        anchor = canon_anchor[:180] or "上章的状态变化"
        direction = volume_direction[:180]
        return RollingChapterPlanContent(
            chapter_number=chapter_number,
            title=f"第{chapter_number}章 新局",
            reader_promise=f"承接《{source_title}》的结果，让读者看到新事实如何改变选择。"[:300],
            opening_hook=f"以“{anchor}”的立即后果开场。"[:300],
            state_change=f"主角因已确认事实做出第 {ordinal} 步不可逆选择。"[:300],
            resource_change="获得一项推进当前卷目标的条件，同时付出可追踪代价。",
            emotional_payoff="先兑现一个小胜利，再暴露更难的后果。",
            ending_cliffhanger=f"卷方向“{direction}”出现新阻力或新机会。"[:300],
            verification="开篇承接定稿事实；章内有因果与代价；章末留下可写的唯一下一步。",
            scene_beats=[
                DirectorSceneBeat(
                    ordinal=1,
                    summary=f"确认“{anchor}”对当下的直接影响。"[:500],
                    state_change="人物意识到旧做法已不可继续。",
                    resource_change="盘点可用资源与缺口。",
                    emotional_turn="从短暂确定转为新的紧迫。",
                    verification="能在最终正文中找到上章事实的具体后果。",
                ),
                DirectorSceneBeat(
                    ordinal=2,
                    summary="人物行动并遭遇有效阻力，用代价换取阶段结果。",
                    state_change="选择改变了下一章的出发条件。",
                    resource_change="至少一项资源有明确增减。",
                    emotional_turn="小胜利与新威胁同时落地。",
                    verification="结果、代价和章末钩子三者因果连接。",
                ),
            ],
        )

    def _approved_body(self, version_id: str) -> str:
        with self.reconciliations.database.connect() as connection:
            row = connection.execute(
                """
                SELECT content FROM chapter_versions
                WHERE id = ? AND is_candidate = 0 AND source = 'approval'
                """,
                (version_id,),
            ).fetchone()
        if row is None:
            raise CanonReconciliationNotFoundError(version_id)
        return str(row["content"])

    def _canon_candidates(
        self,
        *,
        project_id: str,
        chapter_id: str,
        chapter_revision: int,
        approval_version_id: str,
        approved_body: str,
        approved_sha256: str,
        default_event_year: int | None,
    ) -> list[CanonDeltaCandidateDraft]:
        existing = {
            (record.kind, record.subject_key.casefold()): record
            for record in self.reconciliations.list_canon_records(project_id)
        }
        candidates: list[CanonDeltaCandidateDraft] = []
        for extracted in extract_canon_candidates(
            approved_body,
            default_event_year=default_event_year,
        ):
            kind = CanonKind(extracted.kind)
            record = existing.get((kind, extracted.subject_key.casefold()))
            conflicts: list[CanonConflict] = []
            if record is not None:
                same = record.payload.model_dump(mode="json") == extracted.payload
                conflicts.append(
                    CanonConflict(
                        kind=(
                            CanonConflictKind.DUPLICATE
                            if same
                            else CanonConflictKind.SUPERSEDES
                        ),
                        summary=(
                            "与已确认事实一致"
                            if same
                            else "可能替换同一对象的已确认事实"
                        ),
                        existing_record_id=record.id,
                        existing_record_revision=record.revision,
                        existing_record_payload_sha256=record.payload_sha256,
                    )
                )
            span = extracted.evidence
            candidates.append(
                CanonDeltaCandidateDraft(
                    kind=kind,
                    subject_key=extracted.subject_key,
                    summary=extracted.summary,
                    payload=extracted.payload,  # type: ignore[arg-type]
                    evidence=CanonEvidence(
                        approval_version_id=approval_version_id,
                        chapter_id=chapter_id,
                        chapter_revision=chapter_revision,
                        chapter_content_sha256=approved_sha256,
                        start_char=span.start_char,
                        end_char=span.end_char,
                        excerpt=span.excerpt,
                        excerpt_sha256=text_sha256(span.excerpt),
                    ),
                    conflicts=conflicts,
                )
            )
        return candidates

    def _preference_candidates(
        self,
        *,
        approval_id: str,
        source_writing_outcome_id: str | None,
        project_id: str,
        final_body: str,
        final_sha256: str,
    ) -> tuple[list[AuthorPreferenceCandidateDraft], str | None]:
        if source_writing_outcome_id is None:
            return [], "no_adopted_writing_outcome"
        source = self._eligible_preference_source(
            approval_id,
            source_writing_outcome_id,
        )
        if source is None:
            return [], "writing_outcome_not_whole_or_not_in_approval_ancestry"
        candidate_body = str(source["candidate_content"])
        extracted = extract_preference_candidates(candidate_body, final_body)
        if not extracted:
            reason = (
                "author_kept_ai_candidate"
                if candidate_body == final_body
                else "author_adjustment_not_distinct_enough"
            )
            return [], reason
        drafts = [
            AuthorPreferenceCandidateDraft(
                scope_kind=PreferenceScopeKind.PROJECT,
                scope_value=project_id,
                dimension=AuthorPreferenceDimension(item.dimension),
                compact_rule=item.compact_rule,
                confidence=item.confidence,
                comparison_metrics=cast(
                    dict[str, MetricValue],
                    item.comparison_metrics,
                ),
                source_writing_outcome_id=source_writing_outcome_id,
                source_candidate_version_id=str(source["candidate_version_id"]),
                candidate_content_sha256=str(source["candidate_content_sha256"]),
                final_content_sha256=final_sha256,
            )
            for item in extracted
        ]
        return drafts, None

    def _eligible_preference_source(
        self,
        approval_id: str,
        outcome_id: str,
    ) -> Row | None:
        with self.reconciliations.database.connect() as connection:
            row = connection.execute(
                """
                SELECT outcome.*, candidate_version.content AS candidate_content,
                       approval.chapter_version_id AS approval_version_id
                FROM chapter_writing_outcomes outcome
                JOIN chapter_draft_candidate_versions candidate_version
                  ON candidate_version.id = outcome.candidate_version_id
                JOIN chapter_approvals approval ON approval.id = ?
                WHERE outcome.id = ? AND outcome.decision = 'adopted'
                  AND outcome.adoption_mode = 'whole'
                  AND approval.source_writing_outcome_id = outcome.id
                  AND outcome.final_chapter_content_sha256 = outcome.candidate_content_sha256
                """,
                (approval_id, outcome_id),
            ).fetchone()
            if row is None:
                return None
            ancestry = connection.execute(
                """
                WITH RECURSIVE ancestry(id, parent_version_id) AS (
                    SELECT id, parent_version_id FROM chapter_versions WHERE id = ?
                    UNION ALL
                    SELECT version.id, version.parent_version_id
                    FROM chapter_versions version
                    JOIN ancestry ON version.id = ancestry.parent_version_id
                )
                SELECT 1 FROM ancestry WHERE id = ? LIMIT 1
                """,
                (row["approval_version_id"], row["chapter_version_id"]),
            ).fetchone()
        return row if ancestry is not None else None
