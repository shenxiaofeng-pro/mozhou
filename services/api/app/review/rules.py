from datetime import UTC, datetime
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from app.continuity import build_continuity_issues
from app.models import (
    Chapter,
    ContinuityIssueKind,
    ReviewDimension,
    ReviewEvidence,
    ReviewEvidenceKind,
    ReviewFinding,
    ReviewFindingState,
    ReviewSeverity,
    Workspace,
)

LOCAL_REVIEW_DIMENSIONS = frozenset(
    {ReviewDimension.CONTINUITY, ReviewDimension.SERIAL_RHYTHM}
)
EXTERNAL_REVIEW_DIMENSIONS = frozenset(set(ReviewDimension) - LOCAL_REVIEW_DIMENSIONS)

CONTINUITY_KINDS = {
    ContinuityIssueKind.FUTURE_KNOWLEDGE_REVIEW,
    ContinuityIssueKind.OVERDUE_THREAD,
    ContinuityIssueKind.ENTITY_STATE_GAP,
    ContinuityIssueKind.SOURCE_YEAR_MISMATCH,
}
RHYTHM_KINDS = {
    ContinuityIssueKind.RHYTHM_GAP,
    ContinuityIssueKind.REPEATED_BEAT,
}


def _dedupe_key(code: str, evidence: list[ReviewEvidence], title: str) -> str:
    evidence_scope = "|".join(
        f"{item.kind.value}:{item.chapter_id or item.source_type}:"
        f"{item.start_char}:{item.end_char}:{item.source_id}:{item.excerpt or item.label}"
        for item in evidence
    )
    semantic_summary = "".join(title.casefold().split())[:160]
    return sha256(f"{code}|{evidence_scope}|{semantic_summary}".encode()).hexdigest()


def make_finding(
    *,
    job_id: str,
    project_id: str,
    chapter_id: str,
    chapter_revision: int,
    dimension: ReviewDimension,
    severity: ReviewSeverity,
    code: str,
    title: str,
    evidence: list[ReviewEvidence],
    explanation: str,
    suggestion: str,
    suggested_replacement: str | None = None,
    confidence: float,
    created_at: str | None = None,
) -> ReviewFinding:
    dedupe = _dedupe_key(code, evidence, title)
    return ReviewFinding(
        id=str(uuid5(NAMESPACE_URL, f"mozhou:{job_id}:{dimension.value}:{dedupe}")),
        project_id=project_id,
        chapter_id=chapter_id,
        chapter_revision=chapter_revision,
        review_job_id=job_id,
        dimension=dimension,
        severity=severity,
        code=code,
        title=title,
        evidence=evidence,
        explanation=explanation,
        suggestion=suggestion,
        suggested_replacement=suggested_replacement,
        confidence=confidence,
        dedupe_key=dedupe,
        state=ReviewFindingState.OPEN,
        created_at=created_at or datetime.now(UTC).isoformat(),
    )


def build_local_findings(
    workspace: Workspace,
    target: Chapter,
    review_window: list[Chapter],
    dimension: ReviewDimension,
    job_id: str,
) -> list[ReviewFinding]:
    if dimension not in LOCAL_REVIEW_DIMENSIONS:
        raise ValueError("本地规则不支持该审校维度")
    allowed_kinds = CONTINUITY_KINDS if dimension == ReviewDimension.CONTINUITY else RHYTHM_KINDS
    findings = [
        make_finding(
            job_id=job_id,
            project_id=workspace.project.id,
            chapter_id=target.id,
            chapter_revision=target.revision,
            dimension=dimension,
            severity=(
                ReviewSeverity.WARNING
                if issue.severity.value == "warning"
                else ReviewSeverity.INFO
            ),
            code=issue.kind.value,
            title=issue.title,
            evidence=[
                ReviewEvidence(
                    kind=ReviewEvidenceKind.STRUCTURED,
                    source_type="continuity_issue",
                    source_id=issue.id,
                    label="；".join(issue.source_labels) or issue.title,
                )
            ],
            explanation=issue.detail,
            suggestion=_rule_suggestion(issue.kind),
            confidence=0.95,
        )
        for issue in build_continuity_issues(workspace)
        if issue.kind in allowed_kinds
    ]
    if dimension == ReviewDimension.CONTINUITY:
        findings.extend(_knowledge_leakage_findings(workspace, target, job_id))
        findings.extend(_future_fact_leakage_findings(workspace, target, job_id))
    else:
        findings.extend(_rhythm_window_findings(workspace, target, review_window, job_id))
    unique: dict[str, ReviewFinding] = {}
    for finding in findings:
        unique.setdefault(finding.dedupe_key, finding)
    return list(unique.values())


def _knowledge_leakage_findings(
    workspace: Workspace,
    target: Chapter,
    job_id: str,
) -> list[ReviewFinding]:
    findings: list[ReviewFinding] = []
    for knowledge in workspace.future_knowledge:
        if knowledge.status.value == "valid":
            continue
        excerpt = knowledge.content[:240]
        start = target.content.find(excerpt)
        if start < 0:
            continue
        evidence = ReviewEvidence(
            kind=ReviewEvidenceKind.BODY,
            chapter_id=target.id,
            start_char=start,
            end_char=start + len(excerpt),
            excerpt=excerpt,
            label=f"第 {target.chapter_number} 章正文",
        )
        findings.append(
            make_finding(
                job_id=job_id,
                project_id=workspace.project.id,
                chapter_id=target.id,
                chapter_revision=target.revision,
                dimension=ReviewDimension.CONTINUITY,
                severity=ReviewSeverity.CRITICAL,
                code="invalid_future_knowledge_leak",
                title="正文使用了已失效或待复核的未来知识",
                evidence=[evidence],
                explanation=(
                    f"该信息对应 {knowledge.future_year} 年知识，当前状态为"
                    f" {knowledge.status.value}，不能继续当作确定事实。"
                ),
                suggestion="删除确定性断言，或先完成未来知识复核并说明人物当前为何仍能知道。",
                confidence=1.0,
            )
        )
    return findings


def _future_fact_leakage_findings(
    workspace: Workspace,
    target: Chapter,
    job_id: str,
) -> list[ReviewFinding]:
    numbers = {chapter.id: chapter.chapter_number for chapter in workspace.chapters}
    findings: list[ReviewFinding] = []
    for fact in workspace.story_facts:
        source_number = numbers.get(fact.source_chapter_id)
        if source_number is None or source_number <= target.chapter_number:
            continue
        excerpt = fact.content[:240]
        start = target.content.find(excerpt)
        if start < 0:
            continue
        findings.append(
            make_finding(
                job_id=job_id,
                project_id=workspace.project.id,
                chapter_id=target.id,
                chapter_revision=target.revision,
                dimension=ReviewDimension.CONTINUITY,
                severity=ReviewSeverity.CRITICAL,
                code="future_chapter_fact_leak",
                title="本章提前使用了后续章节才成立的事实",
                evidence=[
                    ReviewEvidence(
                        kind=ReviewEvidenceKind.BODY,
                        chapter_id=target.id,
                        start_char=start,
                        end_char=start + len(excerpt),
                        excerpt=excerpt,
                        label=f"事实来源：第 {source_number} 章",
                    )
                ],
                explanation=f"该正式事实的来源章节是第 {source_number} 章，晚于当前章节。",
                suggestion="删除提前泄漏，或把事实成立的因果过程提前并重新确认 Canon。",
                confidence=1.0,
            )
        )
    return findings


def _rhythm_window_findings(
    workspace: Workspace,
    target: Chapter,
    review_window: list[Chapter],
    job_id: str,
) -> list[ReviewFinding]:
    findings: list[ReviewFinding] = []
    if not target.ending_cliffhanger.strip():
        findings.append(
            make_finding(
                job_id=job_id,
                project_id=workspace.project.id,
                chapter_id=target.id,
                chapter_revision=target.revision,
                dimension=ReviewDimension.SERIAL_RHYTHM,
                severity=ReviewSeverity.WARNING,
                code="missing_ending_cliffhanger",
                title="本章没有明确的章尾拉力",
                evidence=[
                    ReviewEvidence(
                        kind=ReviewEvidenceKind.STRUCTURED,
                        source_type="chapter_brief",
                        source_id=target.id,
                        label="章纲字段：章尾悬念为空",
                    )
                ],
                explanation="连载章结束后没有留下下一章必须回答的问题或行动压力。",
                suggestion="补一个由本章因果自然产生的新信息、选择或迫近风险。",
                confidence=0.98,
            )
        )
    hooks = [item.ending_cliffhanger.strip() for item in review_window]
    if len(hooks) >= 3 and hooks[-1] and len(set(hooks[-3:])) == 1:
        findings.append(
            make_finding(
                job_id=job_id,
                project_id=workspace.project.id,
                chapter_id=target.id,
                chapter_revision=target.revision,
                dimension=ReviewDimension.SERIAL_RHYTHM,
                severity=ReviewSeverity.WARNING,
                code="three_chapter_same_cliffhanger",
                title="连续三章使用同一种章尾悬念",
                evidence=[
                    ReviewEvidence(
                        kind=ReviewEvidenceKind.STRUCTURED,
                        source_type="rhythm_window",
                        source_id=target.id,
                        label=f"第 {review_window[-3].chapter_number}–{target.chapter_number} 章：{hooks[-1]}",
                    )
                ],
                explanation="相同的章尾拉力连续重复，会削弱升级感和点击下一章的理由。",
                suggestion="保留主线压力，但把当前章结尾改为新的信息差、代价或不可逆选择。",
                confidence=0.99,
            )
        )
    return findings


def _rule_suggestion(kind: ContinuityIssueKind) -> str:
    return {
        ContinuityIssueKind.FUTURE_KNOWLEDGE_REVIEW: "先复核这条未来知识，再决定正文是否保留确定性表达。",
        ContinuityIssueKind.OVERDUE_THREAD: "在近章安排可验证的推进或回收节点，避免只重复提醒。",
        ContinuityIssueKind.ENTITY_STATE_GAP: "补齐人物或资源的当前状态，再核对本章动作是否可成立。",
        ContinuityIssueKind.SOURCE_YEAR_MISMATCH: "更换覆盖当前年份的资料，或明确标注类比推断。",
        ContinuityIssueKind.RHYTHM_GAP: "补齐读者承诺与情绪兑现，并让两者在正文中形成因果。",
        ContinuityIssueKind.REPEATED_BEAT: "改变本章功能或升级代价，避免相邻章节重复同一节拍。",
    }[kind]
