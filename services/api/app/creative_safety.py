from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class CreativeSafetyProvenance(BaseModel):
    """Immutable proof that a creative operation passed the current safety gate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str
    mode: Literal["legacy", "pattern_adaptation"]
    fingerprint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    adoption_id: str | None = None
    topic_decision_version_id: str | None = None
    topic_revision: int | None = Field(default=None, ge=1)
    topic_content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    profile_version_id: str | None = None
    profile_fingerprint_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    recipe_version_id: str | None = None
    recipe_content_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    blueprint_id: str | None = None
    blueprint_revision: int | None = Field(default=None, ge=0)
    blueprint_content_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    originality_report_id: str | None = None
    originality_input_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    originality_threshold_version: str | None = None
    source_availability: Literal["source_verified", "abstract_only"] | None = None


class CreativeSafetyGate(Protocol):
    def require_creative_safety(
        self,
        project_id: str,
        expected: CreativeSafetyProvenance | None = None,
    ) -> CreativeSafetyProvenance | None: ...
