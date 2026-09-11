from __future__ import annotations

import json
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, Field

from app.ai import (
    AiGateway,
    AiGatewayManager,
    AiNotConfiguredError,
    AiProviderError,
    consume_ai_call_metrics,
)
from app.creative_safety import CreativeSafetyGate, CreativeSafetyProvenance
from app.jobs import AttemptState, Job, JobKind, JobRepository
from app.jobs.runtime import JobExecutionContext, JobExecutionError
from app.providers.models import AiTaskType, ModelProfile
from app.providers.repository import ModelProfileNotFoundError, ModelProfileRepository
from app.repository import OriginalityGateBlockedError
from app.sandbox import NarrativeSandboxService, SandboxAiRoundDraft

SANDBOX_AI_WORKFLOW = "sandbox_ai_round_v1"
SANDBOX_AI_PROMPT_VERSION = "sandbox-ai-prompt-v1"
MAX_SANDBOX_AI_INPUT_CHARACTERS = 120_000
MAX_SANDBOX_AI_OUTPUT_TOKENS = 5_000


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _estimate_cost(
    input_tokens: int,
    output_tokens: int,
    profile: ModelProfile | None,
) -> int | None:
    if profile is None:
        return None
    if (
        profile.input_cost_microusd_per_million is None
        or profile.output_cost_microusd_per_million is None
    ):
        return None
    return (
        input_tokens * profile.input_cost_microusd_per_million
        + output_tokens * profile.output_cost_microusd_per_million
        + 999_999
    ) // 1_000_000


class SandboxAiPreview(BaseModel):
    task_type: Literal["sandbox"] = "sandbox"
    run_id: str
    round_number: int
    state_sha256: str
    snapshot_sha256: str
    profile_id: str | None
    profile_name: str
    provider: str
    model: str
    data_types: list[str]
    content_scope: str
    actor_count: int = Field(ge=5, le=20)
    character_count: int = Field(ge=0)
    estimated_input_tokens: int = Field(ge=0)
    estimated_output_tokens: int = Field(ge=0)
    estimated_cost_microusd: int | None = Field(default=None, ge=0)
    prompt_version: str
    context_sha256: str


class SubmitSandboxAiRoundRequest(BaseModel):
    expected_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirm_external_processing: bool = False
    max_estimated_cost_microusd: int | None = Field(default=None, ge=0)


class SandboxAiJobInput(BaseModel):
    run_id: str
    round_number: int = Field(ge=1, le=10)
    state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_version: str
    creative_safety: CreativeSafetyProvenance | None = None


class SandboxAiService:
    def __init__(
        self,
        sandbox: NarrativeSandboxService,
        jobs: JobRepository,
        manager: AiGatewayManager,
        profiles: ModelProfileRepository,
    ) -> None:
        self.sandbox = sandbox
        self.jobs = jobs
        self.manager = manager
        self.profiles = profiles
        self.creative_safety_gate: CreativeSafetyGate | None = None

    def set_creative_safety_gate(self, gate: CreativeSafetyGate) -> None:
        self.creative_safety_gate = gate

    def preview(self, run_id: str) -> SandboxAiPreview:
        self._require_originality_gate(run_id)
        context = self.sandbox.ai_round_context(run_id)
        context_text = _canonical_json(context)
        if len(context_text) > MAX_SANDBOX_AI_INPUT_CHARACTERS:
            raise ValueError("sandbox_context_too_large")
        profile, profile_name, provider, model = self._preview_profile()
        actor_count = len(context["actors"])
        input_tokens = max(1, (len(context_text) + 1) // 2)
        output_tokens = min(MAX_SANDBOX_AI_OUTPUT_TOKENS, 240 + actor_count * 180)
        return SandboxAiPreview(
            run_id=run_id,
            round_number=int(context["round_number"]),
            state_sha256=str(context["state_sha256"]),
            snapshot_sha256=str(context["snapshot_sha256"]),
            profile_id=profile.id if profile is not None else None,
            profile_name=profile_name,
            provider=provider,
            model=model,
            data_types=[
                "沙盘快照摘要与来源摘要",
                "角色目标、位置、资源、知识、能力和关系",
                "当前分支变量与剩余行动预算",
            ],
            content_scope=(
                f"第 {context['round_number']} 轮 · {actor_count} 个角色 · "
                f"最多 {len(context['source_summaries'])} 条来源摘要"
            ),
            actor_count=actor_count,
            character_count=len(context_text),
            estimated_input_tokens=input_tokens,
            estimated_output_tokens=output_tokens,
            estimated_cost_microusd=_estimate_cost(input_tokens, output_tokens, profile),
            prompt_version=SANDBOX_AI_PROMPT_VERSION,
            context_sha256=sha256(context_text.encode("utf-8")).hexdigest(),
        )

    def submit(self, run_id: str, request: SubmitSandboxAiRoundRequest) -> Job:
        preview = self.preview(run_id)
        if not request.confirm_external_processing:
            raise ValueError("external_processing_not_confirmed")
        if request.expected_state_sha256 != preview.state_sha256:
            raise ValueError("sandbox_state_changed")
        if (
            request.max_estimated_cost_microusd is not None
            and preview.estimated_cost_microusd is not None
            and preview.estimated_cost_microusd > request.max_estimated_cost_microusd
        ):
            raise ValueError("estimated_cost_exceeds_limit")
        context = self.sandbox.ai_round_context(run_id)
        context_text = _canonical_json(context)
        if sha256(context_text.encode("utf-8")).hexdigest() != preview.context_sha256:
            raise ValueError("sandbox_state_changed")
        task_input = SandboxAiJobInput(
            run_id=run_id,
            round_number=preview.round_number,
            state_sha256=preview.state_sha256,
            snapshot_sha256=preview.snapshot_sha256,
            context_sha256=preview.context_sha256,
            prompt_version=SANDBOX_AI_PROMPT_VERSION,
            creative_safety=self._require_originality_gate(run_id),
        )
        idempotency_key = sha256(
            _canonical_json(
                {
                    **task_input.model_dump(mode="json"),
                    "profile_id": preview.profile_id,
                    "model": preview.model,
                }
            ).encode("utf-8")
        ).hexdigest()
        project_id = self._project_id_for_run(run_id)
        job, _created = self.jobs.create_job(
            project_id=project_id,
            kind=JobKind.SANDBOX_AI_ROUND,
            workflow=SANDBOX_AI_WORKFLOW,
            idempotency_key=idempotency_key,
            input_payload=task_input.model_dump(mode="json"),
            provider=preview.provider,
            provider_profile_id=preview.profile_id,
            model=preview.model,
            progress_total=1,
            estimated_calls=1,
        )
        self.jobs.put_artifact(
            job.id,
            kind="sandbox_context",
            artifact_key="sandbox_context",
            payload=context_text,
            content_type="application/json",
            provider="local",
            model=SANDBOX_AI_PROMPT_VERSION,
            metadata={
                "run_id": run_id,
                "round_number": preview.round_number,
                "state_sha256": preview.state_sha256,
                "snapshot_sha256": preview.snapshot_sha256,
                "creative_safety": (
                    task_input.creative_safety.model_dump(mode="json")
                    if task_input.creative_safety is not None
                    else None
                ),
            },
        )
        return self.jobs.get_job(job.id)

    def handle(self, context: JobExecutionContext, job: Job) -> None:
        if job.kind != JobKind.SANDBOX_AI_ROUND or job.workflow != SANDBOX_AI_WORKFLOW:
            raise JobExecutionError("invalid_workflow", "AI 沙盘任务类型无效")
        task_input = SandboxAiJobInput.model_validate(self.jobs.load_input(job.id))
        if self.sandbox.has_round_for_job(job.id):
            self.jobs.update_progress(
                job.id,
                current=1,
                total=1,
                step=f"AI 第 {task_input.round_number} 轮已从既有裁决恢复",
            )
            return
        try:
            current_safety = self._require_originality_gate(
                task_input.run_id, task_input.creative_safety
            )
        except (ValueError, OriginalityGateBlockedError) as error:
            code = (
                "originality_gate_blocked"
                if str(error) == "originality_gate_blocked"
                else "creative_safety_changed"
            )
            raise JobExecutionError(
                code,
                "创作安全依赖已变化，请重新预览后提交；模型未调用",
            ) from error
        if (
            current_safety is not None
            and current_safety.mode == "pattern_adaptation"
            and task_input.creative_safety is None
        ):
            raise JobExecutionError(
                "creative_safety_changed",
                "旧任务缺少创作安全快照，请重新预览后提交；模型未调用",
            )
        rebuilt = self.sandbox.ai_round_context(task_input.run_id)
        rebuilt_text = _canonical_json(rebuilt)
        if (
            str(rebuilt["state_sha256"]) != task_input.state_sha256
            or int(rebuilt["round_number"]) != task_input.round_number
            or sha256(rebuilt_text.encode("utf-8")).hexdigest() != task_input.context_sha256
        ):
            raise JobExecutionError(
                "sandbox_state_changed",
                "沙盘状态已经变化，请重新预览后提交",
            )
        frozen = self.jobs.find_artifact(job.id, "sandbox_context")
        if frozen is None or frozen.payload != rebuilt_text:
            raise JobExecutionError(
                "sandbox_context_invalid",
                "冻结的沙盘上下文完整性校验失败，未调用模型",
            )
        context.checkpoint()
        result_artifact = self.jobs.find_artifact(job.id, "sandbox_ai_proposal")
        if result_artifact is None:
            gateway = self._gateway_for_job(job)
            attempt = self.jobs.start_attempt(
                job.id,
                provider=job.provider,
                provider_profile_id=job.provider_profile_id,
                model=job.model,
            )
            try:
                proposal = gateway.propose_sandbox_round(rebuilt_text)
                metrics = consume_ai_call_metrics(gateway)
                self.jobs.put_artifact(
                    job.id,
                    kind="sandbox_ai_proposal",
                    artifact_key="sandbox_ai_proposal",
                    payload=proposal.model_dump_json(),
                    content_type="application/json",
                    provider=job.provider,
                    provider_profile_id=job.provider_profile_id,
                    model=job.model,
                    metadata={
                        "run_id": task_input.run_id,
                        "round_number": task_input.round_number,
                        "prompt_version": task_input.prompt_version,
                        "context_sha256": task_input.context_sha256,
                        "creative_safety": (
                            task_input.creative_safety.model_dump(mode="json")
                            if task_input.creative_safety is not None
                            else None
                        ),
                    },
                )
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
            except AiProviderError as error:
                self.jobs.finish_attempt(
                    attempt.id,
                    AttemptState.FAILED,
                    duration_ms=error.duration_ms,
                    error_code=error.category.value,
                    error_message=error.safe_message,
                )
                raise JobExecutionError(error.category.value, error.safe_message) from error
        else:
            proposal = SandboxAiRoundDraft.model_validate_json(result_artifact.payload)
        context.checkpoint()
        try:
            self._require_originality_gate(task_input.run_id, task_input.creative_safety)
        except (ValueError, OriginalityGateBlockedError) as error:
            raise JobExecutionError(
                "creative_safety_changed",
                "创作安全依赖已变化，未应用沙盘候选",
            ) from error
        self.sandbox.apply_ai_round(
            task_input.run_id,
            proposal,
            expected_state_sha256=task_input.state_sha256,
            job_id=job.id,
        )
        self.jobs.update_progress(
            job.id,
            current=1,
            total=1,
            step=f"AI 第 {task_input.round_number} 轮已完成规则裁决",
        )

    def _preview_profile(self) -> tuple[ModelProfile | None, str, str, str]:
        profile = self.profiles.get_task_profile(AiTaskType.SANDBOX)
        if profile is not None:
            gateway = self.manager.gateway_for(profile.id)
            if not gateway.status().configured:
                raise AiNotConfiguredError
            return profile, profile.name, profile.provider.value, profile.model
        status = self.manager.status()
        if not status.configured:
            raise AiNotConfiguredError
        active_profile: ModelProfile | None = None
        if status.profile_id is not None:
            try:
                active_profile = self.profiles.get_profile(status.profile_id)
            except ModelProfileNotFoundError:
                active_profile = None
        return (
            active_profile,
            status.profile_name or "当前会话线路",
            status.provider.value,
            status.model,
        )

    def _gateway_for_job(self, job: Job) -> AiGateway:
        gateway = self.manager.gateway_for(job.provider_profile_id)
        status = gateway.status()
        if (
            not status.configured
            or status.provider.value != job.provider
            or status.model != job.model
            or status.profile_id != job.provider_profile_id
        ):
            raise JobExecutionError(
                "provider_unavailable",
                "任务使用的沙盘模型配置当前不可用，请恢复配置后重试",
            )
        return gateway

    def _project_id_for_run(self, run_id: str) -> str:
        with self.sandbox.database.connect() as connection:
            row = connection.execute(
                "SELECT project_id FROM sandbox_runs WHERE id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise ValueError("sandbox_run_not_found")
        return str(row["project_id"])

    def _require_originality_gate(
        self,
        run_id: str,
        expected: CreativeSafetyProvenance | None = None,
    ) -> CreativeSafetyProvenance | None:
        with self.sandbox.database.connect() as connection:
            row = connection.execute(
                "SELECT project_id FROM sandbox_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if row is None:
                raise ValueError("sandbox_run_not_found")
            project_id = str(row["project_id"])
            blocked = connection.execute(
                """
                SELECT 1 FROM reference_pattern_applications
                WHERE project_id = ? AND lifecycle_state = 'active'
                  AND originality_status != 'passed'
                LIMIT 1
                """,
                (project_id,),
            ).fetchone()
        if blocked is not None:
            raise ValueError("originality_gate_blocked")
        if self.creative_safety_gate is None:
            return None
        return self.creative_safety_gate.require_creative_safety(project_id, expected)
