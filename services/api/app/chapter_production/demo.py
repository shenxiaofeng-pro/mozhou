from __future__ import annotations

from app.models import ReviewDimension, ReviewSeverity

from .models import (
    AdapterOutlineResult,
    AdapterReviewResult,
    AdapterTextResult,
    CandidateReviewDraft,
    CandidateReviewFinding,
    ChapterOutline,
    DraftGenerationInput,
    OutlineGenerationInput,
    ReviewGenerationInput,
    RewriteGenerationInput,
    RewriteIntent,
)


class DeterministicDemoChapterAdapter:
    """Offline adapter using exactly the same interface as paid model adapters."""

    provider = "demo"
    model = "chapter-production-replay-v1"

    def __init__(self) -> None:
        self.outline_calls = 0
        self.draft_calls = 0
        self.rewrite_calls = 0
        self.review_calls = 0

    def propose_outline(self, request: OutlineGenerationInput) -> AdapterOutlineResult:
        self.outline_calls += 1
        intent = request.author_intent or "让主角用一次主动选择改变局面"
        return AdapterOutlineResult(
            outline=ChapterOutline(
                title="先手",
                reader_promise=f"读者将看到：{intent}",
                opening_hook="坏消息提前抵达，留给主角的时间只剩一刻钟。",
                state_change="主角从被动等待转为主动承担风险。",
                emotional_payoff="此前的质疑者第一次给出有限信任。",
                ending_cliffhanger="刚解决眼前危机，更大的代价已经找上门。",
                scene_beats=[
                    "坏消息落地并限定时间",
                    "主角付出代价换取行动窗口",
                    "阶段兑现后暴露更大风险",
                ],
            ),
            prompt_version="chapter-outline-demo-v1",
        )

    def draft_chapter(self, request: DraftGenerationInput) -> AdapterTextResult:
        self.draft_calls += 1
        outline = request.outline
        content = (
            f"{outline.opening_hook}\n\n"
            f"{outline.reader_promise}\n\n"
            f"{outline.state_change}\n\n"
            f"{outline.emotional_payoff}\n\n"
            f"{outline.ending_cliffhanger}"
        )
        return AdapterTextResult(content=content, prompt_version="chapter-draft-demo-v1")

    def rewrite_selection(self, request: RewriteGenerationInput) -> AdapterTextResult:
        self.rewrite_calls += 1
        selected = request.selected_text
        replacements = {
            RewriteIntent.EXPAND: f"{selected}，他顺着这个判断又向前逼近了一步",
            RewriteIntent.COMPRESS: selected[: max(1, len(selected) // 2)],
            RewriteIntent.REWRITE: f"换一个方向看，{selected}",
            RewriteIntent.STRENGTHEN_CONFLICT: f"危机骤然加重：{selected}",
            RewriteIntent.STRENGTHEN_EMOTION: f"他压住翻涌的情绪，{selected}",
            RewriteIntent.CUSTOM: f"{request.custom_instruction}：{selected}",
        }
        return AdapterTextResult(
            content=replacements[request.intent],
            prompt_version="chapter-rewrite-demo-v1",
        )

    def review_candidate(self, request: ReviewGenerationInput) -> AdapterReviewResult:
        self.review_calls += 1
        character_count = len(request.candidate_content)
        return AdapterReviewResult(
            review=CandidateReviewDraft(
                findings=[
                    CandidateReviewFinding(
                        dimension=dimension,
                        severity=ReviewSeverity.INFO,
                        summary=f"{dimension.value} 维度已检查 {character_count} 字候选稿。",
                        suggestion="由作者结合本章目标决定是否调整。",
                    )
                    for dimension in ReviewDimension
                ]
            ),
            prompt_version="chapter-review-demo-v1",
        )
