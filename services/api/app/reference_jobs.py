import json
from dataclasses import dataclass
from hashlib import sha256

from app.ai import (
    AiGateway,
    AiGatewayManager,
    AiNotConfiguredError,
    AiProviderError,
    consume_ai_call_metrics,
)
from app.jobs.models import AttemptState, ChunkState, Job, JobChunk, JobKind
from app.jobs.repository import JobRepository
from app.jobs.runtime import JobExecutionContext, JobExecutionError
from app.models import (
    ReferenceBookAnalysis,
    ReferenceChunkAnalysis,
    ReferenceSynthesisProposal,
    ReferenceSynthesisRequest,
)
from app.reference_lab import ReferenceAnalysisInput, segment_reference_text
from app.repository import InvalidReferenceSelectionError, ProjectRepository

REFERENCE_JOB_PROMPT_VERSION = "reference-map-book-fusion-v1"
REFERENCE_MAP_TARGET_CHARACTERS = 50_000


@dataclass(frozen=True)
class PlannedReferenceChunk:
    kind: JobKind
    ordinal: int
    artifact_key: str
    input_payload: dict[str, object]


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _job_idempotency_key(
    request: ReferenceSynthesisRequest,
    provider: str,
    provider_profile_id: str | None,
    model: str,
) -> str:
    payload = {
        "selected_segment_ids": request.selected_segment_ids,
        "author_focus": request.author_focus,
        "provider": provider,
        "provider_profile_id": provider_profile_id,
        "model": model,
        "prompt_version": REFERENCE_JOB_PROMPT_VERSION,
    }
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def plan_reference_chunks(
    segments: list[ReferenceAnalysisInput],
) -> list[PlannedReferenceChunk]:
    planned: list[PlannedReferenceChunk] = []
    work_order: list[str] = []
    work_titles: dict[str, str] = {}
    segment_ids_by_work: dict[str, list[str]] = {}

    for segment in segments:
        if segment.work_id not in work_titles:
            work_order.append(segment.work_id)
            work_titles[segment.work_id] = segment.work_title
            segment_ids_by_work[segment.work_id] = []
        segment_ids_by_work[segment.work_id].append(segment.segment_id)
        for chunk in segment_reference_text(
            segment.content,
            target_characters=REFERENCE_MAP_TARGET_CHARACTERS,
        ):
            planned.append(PlannedReferenceChunk(
                kind=JobKind.REFERENCE_SEGMENT_MAP,
                ordinal=len(planned),
                artifact_key=(
                    f"map:{segment.segment_id}:{chunk.start_char}:{chunk.end_char}"
                ),
                input_payload={
                    "segment_id": segment.segment_id,
                    "work_id": segment.work_id,
                    "work_title": segment.work_title,
                    "segment_ordinal": segment.ordinal,
                    "chunk_start": chunk.start_char,
                    "chunk_end": chunk.end_char,
                    "absolute_start": segment.start_char + chunk.start_char,
                    "absolute_end": segment.start_char + chunk.end_char,
                },
            ))

    for work_id in work_order:
        planned.append(PlannedReferenceChunk(
            kind=JobKind.REFERENCE_BOOK_REDUCE,
            ordinal=len(planned),
            artifact_key=f"book:{work_id}",
            input_payload={
                "work_id": work_id,
                "work_title": work_titles[work_id],
                "source_segment_ids": segment_ids_by_work[work_id],
            },
        ))

    planned.append(PlannedReferenceChunk(
        kind=JobKind.REFERENCE_FUSION,
        ordinal=len(planned),
        artifact_key="fusion",
        input_payload={
            "work_ids": work_order,
            "allowed_source_segment_ids": [segment.segment_id for segment in segments],
        },
    ))
    return planned


class ReferenceJobService:
    def __init__(
        self,
        repository: ProjectRepository,
        jobs: JobRepository,
        manager: AiGatewayManager,
    ) -> None:
        self.repository = repository
        self.jobs = jobs
        self.manager = manager

    def submit(self, project_id: str, request: ReferenceSynthesisRequest) -> Job:
        if not request.confirm_external_processing:
            raise InvalidReferenceSelectionError("external_processing_not_confirmed")
        status = self.manager.status()
        if not status.configured:
            raise AiNotConfiguredError
        segments = self.repository.get_reference_segments_for_analysis(
            project_id,
            request.selected_segment_ids,
        )
        plan = plan_reference_chunks(segments)
        job, _created = self.jobs.create_job(
            project_id=project_id,
            kind=JobKind.REFERENCE_FUSION,
            idempotency_key=_job_idempotency_key(
                request,
                status.provider.value,
                status.profile_id,
                status.model,
            ),
            input_payload={
                **request.model_dump(mode="json"),
                "prompt_version": REFERENCE_JOB_PROMPT_VERSION,
            },
            provider=status.provider.value,
            provider_profile_id=status.profile_id,
            model=status.model,
            progress_total=len(plan),
            estimated_calls=len(plan),
        )
        self._ensure_chunks(job.id, plan)
        return self.jobs.get_job(job.id)

    def handle(self, context: JobExecutionContext, job: Job) -> None:
        request = ReferenceSynthesisRequest.model_validate(self.jobs.load_input(job.id))
        gateway = self.manager.gateway_for(job.provider_profile_id)
        status = gateway.status()
        if (
            not status.configured
            or status.provider.value != job.provider
            or status.profile_id != job.provider_profile_id
            or status.model != job.model
        ):
            raise JobExecutionError(
                "provider_unavailable",
                "任务使用的模型配置当前不可用，请恢复配置后重试",
            )
        segments = self.repository.get_reference_segments_for_analysis(
            job.project_id,
            request.selected_segment_ids,
        )
        plan = plan_reference_chunks(segments)
        chunks = self._ensure_chunks(job.id, plan)
        segment_by_id = {segment.segment_id: segment for segment in segments}
        completed = 0
        self.jobs.update_progress(
            job.id,
            current=completed,
            total=len(plan),
            step="准备恢复已完成的拆书结果",
        )

        for item, chunk in zip(plan, chunks, strict=True):
            context.checkpoint()
            artifact = self.jobs.find_artifact(job.id, item.artifact_key)
            if artifact is not None:
                if chunk.state != ChunkState.SUCCEEDED:
                    if chunk.state != ChunkState.RUNNING:
                        chunk = self.jobs.transition_chunk(chunk.id, ChunkState.RUNNING)
                    self.jobs.transition_chunk(chunk.id, ChunkState.SUCCEEDED)
                completed += 1
                self.jobs.update_progress(
                    job.id,
                    current=completed,
                    total=len(plan),
                    step=self._step_label(item, cached=True),
                )
                continue
            if chunk.state == ChunkState.SUCCEEDED:
                raise JobExecutionError("missing_artifact", "已完成任务块缺少产物，无法安全继续")
            if chunk.state != ChunkState.RUNNING:
                chunk = self.jobs.transition_chunk(chunk.id, ChunkState.RUNNING)
            self.jobs.update_progress(
                job.id,
                current=completed,
                total=len(plan),
                step=self._step_label(item, cached=False),
            )
            attempt = self.jobs.start_attempt(
                job.id,
                chunk_id=chunk.id,
                provider=job.provider,
                provider_profile_id=job.provider_profile_id,
                model=job.model,
            )
            try:
                payload, metadata = self._execute_chunk(
                    item,
                    request,
                    segment_by_id,
                    plan,
                    gateway,
                    job.id,
                )
            except AiProviderError as error:
                metrics = consume_ai_call_metrics(gateway)
                self.jobs.finish_attempt(
                    attempt.id,
                    AttemptState.FAILED,
                    input_tokens=metrics.usage.input_tokens if metrics else None,
                    output_tokens=metrics.usage.output_tokens if metrics else None,
                    duration_ms=error.duration_ms or (metrics.duration_ms if metrics else None),
                    estimated_cost_microusd=(
                        metrics.estimated_cost_microusd if metrics else None
                    ),
                    error_code=error.category.value,
                    error_message=error.safe_message,
                )
                self.jobs.transition_chunk(
                    chunk.id,
                    ChunkState.FAILED,
                    error_code=error.category.value,
                    error_message=error.safe_message,
                )
                raise JobExecutionError(
                    error.category.value,
                    error.safe_message,
                ) from error
            except Exception as error:
                self.jobs.finish_attempt(
                    attempt.id,
                    AttemptState.FAILED,
                    error_code="provider_error",
                    error_message="模型服务未完成当前拆书块",
                )
                self.jobs.transition_chunk(
                    chunk.id,
                    ChunkState.FAILED,
                    error_code="provider_error",
                    error_message="模型服务未完成当前拆书块",
                )
                if isinstance(error, JobExecutionError):
                    raise
                raise JobExecutionError(
                    "provider_error",
                    "模型服务未完成当前拆书块，重试会复用此前结果",
                ) from error
            self.jobs.put_artifact(
                job.id,
                chunk_id=chunk.id,
                kind=item.kind.value,
                artifact_key=item.artifact_key,
                payload=payload,
                content_type="application/json",
                metadata=metadata,
                provider=job.provider,
                provider_profile_id=job.provider_profile_id,
                model=job.model,
            )
            metrics = consume_ai_call_metrics(gateway)
            self.jobs.finish_attempt(
                attempt.id,
                AttemptState.SUCCEEDED,
                input_tokens=metrics.usage.input_tokens if metrics else None,
                output_tokens=metrics.usage.output_tokens if metrics else None,
                duration_ms=metrics.duration_ms if metrics else None,
                estimated_cost_microusd=(
                    metrics.estimated_cost_microusd if metrics else None
                ),
            )
            self.jobs.transition_chunk(chunk.id, ChunkState.SUCCEEDED)
            completed += 1
            self.jobs.update_progress(
                job.id,
                current=completed,
                total=len(plan),
                step=self._step_label(item, cached=False),
            )

        final_artifact = self.jobs.find_artifact(job.id, "fusion")
        if final_artifact is None:
            raise JobExecutionError("missing_artifact", "多书合成产物不存在")
        proposal = ReferenceSynthesisProposal.model_validate_json(final_artifact.payload)
        self._validate_proposal_sources(proposal, set(request.selected_segment_ids))
        self.repository.save_reference_pattern_card(
            job.project_id,
            request.selected_segment_ids,
            request.author_focus,
            proposal,
            job.provider,
            job.model,
            source_job_id=job.id,
        )

    def _ensure_chunks(
        self,
        job_id: str,
        plan: list[PlannedReferenceChunk],
    ) -> list[JobChunk]:
        for item in plan:
            self.jobs.ensure_chunk(
                job_id,
                kind=item.kind,
                ordinal=item.ordinal,
                idempotency_key=item.artifact_key,
                input_payload=item.input_payload,
            )
        chunks = self.jobs.list_chunks(job_id)
        if len(chunks) != len(plan):
            raise JobExecutionError("invalid_plan", "拆书任务计划不完整")
        return chunks

    def _execute_chunk(
        self,
        item: PlannedReferenceChunk,
        request: ReferenceSynthesisRequest,
        segment_by_id: dict[str, ReferenceAnalysisInput],
        plan: list[PlannedReferenceChunk],
        gateway: AiGateway,
        job_id: str,
    ) -> tuple[str, dict[str, object]]:
        if item.kind == JobKind.REFERENCE_SEGMENT_MAP:
            segment_id = str(item.input_payload["segment_id"])
            segment = segment_by_id[segment_id]
            raw_chunk_start = item.input_payload["chunk_start"]
            raw_chunk_end = item.input_payload["chunk_end"]
            if not isinstance(raw_chunk_start, int) or not isinstance(raw_chunk_end, int):
                raise JobExecutionError("invalid_plan", "拆书字符范围无效")
            chunk_start = raw_chunk_start
            chunk_end = raw_chunk_end
            analysis = gateway.analyze_reference_chunk(segment, chunk_start, chunk_end)
            if not isinstance(analysis, ReferenceChunkAnalysis):
                raise AiProviderError("AI 未返回可用的区段分析")
            return analysis.model_dump_json(), dict(item.input_payload)

        if item.kind == JobKind.REFERENCE_BOOK_REDUCE:
            work_id = str(item.input_payload["work_id"])
            mapped: list[dict[str, object]] = []
            for map_item in plan:
                if (
                    map_item.kind != JobKind.REFERENCE_SEGMENT_MAP
                    or map_item.input_payload["work_id"] != work_id
                ):
                    continue
                artifact = self.jobs.find_artifact(job_id, map_item.artifact_key)
                if artifact is None:
                    raise JobExecutionError("missing_map_artifact", "单书归纳缺少区段结果")
                mapped.append({
                    **map_item.input_payload,
                    "analysis": ReferenceChunkAnalysis.model_validate_json(
                        artifact.payload
                    ).model_dump(mode="json"),
                })
            work_title = str(item.input_payload["work_title"])
            analysis = gateway.reduce_reference_book(
                work_id,
                work_title,
                mapped,
                request.author_focus,
            )
            if not isinstance(analysis, ReferenceBookAnalysis):
                raise AiProviderError("AI 未返回可用的单书归纳")
            raw_source_ids = item.input_payload["source_segment_ids"]
            if not isinstance(raw_source_ids, list) or not all(
                isinstance(source_id, str) for source_id in raw_source_ids
            ):
                raise JobExecutionError("invalid_plan", "单书来源计划无效")
            allowed_ids = set(raw_source_ids)
            if (
                analysis.work_id != work_id
                or analysis.work_title != work_title
                or not set(analysis.source_segment_ids) <= allowed_ids
            ):
                raise AiProviderError("AI 单书归纳引用了无效来源")
            return analysis.model_dump_json(), dict(item.input_payload)

        if item.kind == JobKind.REFERENCE_FUSION:
            books: list[ReferenceBookAnalysis] = []
            for book_item in plan:
                if book_item.kind != JobKind.REFERENCE_BOOK_REDUCE:
                    continue
                artifact = self.jobs.find_artifact(job_id, book_item.artifact_key)
                if artifact is None:
                    raise JobExecutionError("missing_book_artifact", "多书合成缺少单书结果")
                books.append(ReferenceBookAnalysis.model_validate_json(artifact.payload))
            proposal = gateway.fuse_reference_books(
                books,
                request.selected_segment_ids,
                request.author_focus,
            )
            if not isinstance(proposal, ReferenceSynthesisProposal):
                raise AiProviderError("AI 未返回可用的多书结构方案")
            self._validate_proposal_sources(proposal, set(request.selected_segment_ids))
            return proposal.model_dump_json(), dict(item.input_payload)

        raise JobExecutionError("unsupported_chunk", "不支持的拆书任务块")

    @staticmethod
    def _validate_proposal_sources(
        proposal: ReferenceSynthesisProposal,
        allowed_ids: set[str],
    ) -> None:
        dimensions = (
            proposal.era,
            proposal.core_desire,
            proposal.conflict_causality,
            proposal.resource_system,
            proposal.key_scene_sequence,
            proposal.ending,
        )
        if any(not set(dimension.source_segment_ids) <= allowed_ids for dimension in dimensions):
            raise AiProviderError("AI 返回了无效来源")

    @staticmethod
    def _step_label(item: PlannedReferenceChunk, *, cached: bool) -> str:
        suffix = "（复用已完成结果）" if cached else ""
        if item.kind == JobKind.REFERENCE_SEGMENT_MAP:
            return f"分析第 {item.ordinal + 1} 个 5 万字块{suffix}"
        if item.kind == JobKind.REFERENCE_BOOK_REDUCE:
            return f"归纳《{item.input_payload['work_title']}》{suffix}"
        return f"跨书合成六维结构{suffix}"
