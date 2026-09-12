from __future__ import annotations

from typing import ClassVar, Protocol

from app.context import (
    CreativeContextCompileRequest,
    CreativeContextPurpose,
    CreativeContextService,
    CreativeContextSubject,
    CreativeContextSubjectKind,
)
from app.repository import ProjectRepository

from .models import (
    AdapterOutlineResult,
    AdapterReviewResult,
    AdapterTextResult,
    CreativeContextSnapshot,
    DraftGenerationInput,
    OutlineGenerationInput,
    ReviewGenerationInput,
    RewriteGenerationInput,
)


class ChapterProductionModelAdapter(Protocol):
    """All real and demo models enter ChapterProduction through this contract."""

    @property
    def provider(self) -> str: ...

    @property
    def model(self) -> str: ...

    def propose_outline(self, request: OutlineGenerationInput) -> AdapterOutlineResult: ...

    def draft_chapter(self, request: DraftGenerationInput) -> AdapterTextResult: ...

    def rewrite_selection(self, request: RewriteGenerationInput) -> AdapterTextResult: ...

    def review_candidate(self, request: ReviewGenerationInput) -> AdapterReviewResult: ...


class ChapterCreativeContextProvider(Protocol):
    """Narrow M32 boundary used by every ChapterProduction model call."""

    def compile(
        self,
        *,
        project_id: str,
        chapter_id: str,
        chapter_revision: int,
        purpose: CreativeContextPurpose,
        token_budget: int,
        author_intent: str = "",
    ) -> CreativeContextSnapshot: ...

    def require_current(self, snapshot: CreativeContextSnapshot) -> None: ...


class CreativeContextServiceProvider:
    """Production bridge; it never assembles prompt context itself."""

    _ALLOWED_PURPOSES: ClassVar[frozenset[CreativeContextPurpose]] = frozenset(
        {
            CreativeContextPurpose.BRIEF,
            CreativeContextPurpose.DRAFT,
            CreativeContextPurpose.CANDIDATE_REVIEW,
        }
    )

    def __init__(
        self,
        projects: ProjectRepository,
        creative_context: CreativeContextService,
    ) -> None:
        self.projects = projects
        self.creative_context = creative_context

    def compile(
        self,
        *,
        project_id: str,
        chapter_id: str,
        chapter_revision: int,
        purpose: CreativeContextPurpose,
        token_budget: int,
        author_intent: str = "",
    ) -> CreativeContextSnapshot:
        if purpose not in self._ALLOWED_PURPOSES:
            raise ValueError("chapter_production_context_purpose_not_allowed")
        workspace = self.projects.get_workspace(project_id)
        packet = self.creative_context.compile(
            workspace,
            CreativeContextCompileRequest(
                purpose=purpose,
                subject=CreativeContextSubject(
                    kind=CreativeContextSubjectKind.CHAPTER,
                    id=chapter_id,
                    revision=chapter_revision,
                ),
                token_budget=token_budget,
                author_intent=author_intent,
            ),
        )
        self.creative_context.require_usable(packet)
        return CreativeContextSnapshot(
            purpose=packet.purpose,
            packet_id=packet.id,
            packet_sha256=packet.packet_sha256,
            dependency_fingerprint_sha256=packet.dependency_fingerprint_sha256,
            compiler_version=packet.compiler_version,
            profile_fingerprint_sha256=packet.profile_fingerprint_sha256,
            rendered_context=packet.rendered_context,
        )

    def require_current(self, snapshot: CreativeContextSnapshot) -> None:
        packet = self.creative_context.contexts.get_packet(snapshot.packet_id)
        if (
            packet.purpose != snapshot.purpose
            or packet.packet_sha256 != snapshot.packet_sha256
            or packet.dependency_fingerprint_sha256 != snapshot.dependency_fingerprint_sha256
            or packet.compiler_version != snapshot.compiler_version
            or packet.profile_fingerprint_sha256 != snapshot.profile_fingerprint_sha256
        ):
            raise ValueError("creative_context_snapshot_changed")
        self.creative_context.require_current(packet)
