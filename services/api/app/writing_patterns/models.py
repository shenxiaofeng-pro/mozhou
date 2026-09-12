from __future__ import annotations

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import CraftPatternAssetType, CraftPatternDimension


class WritingPatternPurpose(StrEnum):
    LEARN = "learn"
    COUNTEREXAMPLE = "counterexample"


class WritingPatternStrategy(StrEnum):
    PRESERVE_FUNCTION = "preserve_function"
    TRANSFORM = "transform"
    AVOID = "avoid"


class WritingPatternStage(StrEnum):
    STARTUP = "startup"
    VOLUME = "volume"
    ROLLING = "rolling"
    CHAPTER_BRIEF = "chapter_brief"
    CHAPTER_DRAFT = "chapter_draft"
    REWRITE = "rewrite"
    REVIEW = "review"


class WritingPatternSafetyBasis(StrEnum):
    SOURCE_VERIFIED = "source_verified"
    ABSTRACT_ONLY = "abstract_only"


class WritingPatternLifecycleState(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class WritingPatternConflictResolution(StrEnum):
    CHOOSE_SOURCE = "choose_source"
    COMBINE_AS_TRANSFORM = "combine_as_transform"
    EXCLUDE_ALL = "exclude_all"


class WritingPatternWorkFingerprint(BaseModel):
    basis: Literal["content_sha256", "abstract_lineage"]
    identity_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class WritingPatternRecipeEntryInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    asset_version_id: str = Field(min_length=36, max_length=36)
    asset_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dimension: CraftPatternDimension
    pattern_name: str = Field(min_length=1, max_length=120)
    purpose: WritingPatternPurpose
    strategy: WritingPatternStrategy
    weight: int = Field(ge=1, le=100)
    applicable_stages: list[WritingPatternStage] = Field(min_length=1, max_length=7)
    chapter_start: int | None = Field(default=None, ge=1, le=100_000)
    chapter_end: int | None = Field(default=None, ge=1, le=100_000)
    note: str = Field(default="", max_length=1000)

    @field_validator("asset_version_id")
    @classmethod
    def validate_asset_id(cls, value: str) -> str:
        try:
            if str(UUID(value)) != value:
                raise ValueError
        except (TypeError, ValueError) as error:
            raise ValueError("写作配方资产标识无效") from error
        return value

    @field_validator("pattern_name", "note")
    @classmethod
    def reject_null_bytes(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("写作配方文本不能包含空字节")
        return value

    @field_validator("applicable_stages")
    @classmethod
    def validate_stages(
        cls, value: list[WritingPatternStage]
    ) -> list[WritingPatternStage]:
        if len(value) != len(set(value)):
            raise ValueError("适用阶段不能重复")
        return value

    @model_validator(mode="after")
    def validate_chapter_range(self) -> WritingPatternRecipeEntryInput:
        if (
            self.purpose == WritingPatternPurpose.COUNTEREXAMPLE
            and self.strategy == WritingPatternStrategy.PRESERVE_FUNCTION
        ):
            raise ValueError("反例不能作为必须保留的写作功能")
        if (self.chapter_start is None) != (self.chapter_end is None):
            raise ValueError("章节范围必须同时提供起止值")
        if (
            self.chapter_start is not None
            and self.chapter_end is not None
            and self.chapter_end < self.chapter_start
        ):
            raise ValueError("章节范围无效")
        return self


class WritingPatternConflictDecisionInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    conflict_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    resolution: WritingPatternConflictResolution
    chosen_entry_key: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )

    @model_validator(mode="after")
    def validate_choice(self) -> WritingPatternConflictDecisionInput:
        if self.resolution == WritingPatternConflictResolution.CHOOSE_SOURCE:
            if self.chosen_entry_key is None:
                raise ValueError("选择来源时必须指定条目")
        elif self.chosen_entry_key is not None:
            raise ValueError("当前冲突处理不接受选中条目")
        return self


class RecipeSourceSnapshot(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    entry_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    asset_version_id: str = Field(min_length=36, max_length=36)
    asset_series_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    asset_version: int = Field(ge=1)
    asset_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    asset_type: CraftPatternAssetType = CraftPatternAssetType.STAGE
    dimension: CraftPatternDimension
    pattern_name: str = Field(min_length=1, max_length=120)
    transferable_rule: str = Field(min_length=1, max_length=1000)
    adaptation_risk: str = Field(min_length=1, max_length=600)
    purpose: WritingPatternPurpose
    strategy: WritingPatternStrategy
    weight: int = Field(ge=1, le=100)
    applicable_stages: list[WritingPatternStage] = Field(min_length=1, max_length=7)
    chapter_start: int | None = Field(default=None, ge=1, le=100_000)
    chapter_end: int | None = Field(default=None, ge=1, le=100_000)
    note: str = Field(default="", max_length=1000)
    source_work_fingerprints: list[WritingPatternWorkFingerprint] = Field(
        min_length=1,
        max_length=5,
    )
    source_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("asset_version_id")
    @classmethod
    def validate_asset_id(cls, value: str) -> str:
        try:
            if str(UUID(value)) != value:
                raise ValueError
        except (TypeError, ValueError) as error:
            raise ValueError("写作配方资产标识无效") from error
        return value

    @field_validator(
        "pattern_name",
        "transferable_rule",
        "adaptation_risk",
        "note",
    )
    @classmethod
    def reject_snapshot_null_bytes(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("写作配方快照不能包含空字节")
        return value

    @field_validator("applicable_stages")
    @classmethod
    def validate_snapshot_stages(
        cls, value: list[WritingPatternStage]
    ) -> list[WritingPatternStage]:
        if len(value) != len(set(value)):
            raise ValueError("适用阶段不能重复")
        return value

    @field_validator("source_work_fingerprints")
    @classmethod
    def validate_work_fingerprints(
        cls,
        value: list[WritingPatternWorkFingerprint],
    ) -> list[WritingPatternWorkFingerprint]:
        keys = [item.identity_sha256 for item in value]
        if len(keys) != len(set(keys)):
            raise ValueError("来源作品指纹不能重复")
        return value

    @model_validator(mode="after")
    def validate_snapshot_range(self) -> RecipeSourceSnapshot:
        if (
            self.purpose == WritingPatternPurpose.COUNTEREXAMPLE
            and self.strategy == WritingPatternStrategy.PRESERVE_FUNCTION
        ):
            raise ValueError("反例不能作为必须保留的写作功能")
        if (self.chapter_start is None) != (self.chapter_end is None):
            raise ValueError("章节范围必须同时提供起止值")
        if (
            self.chapter_start is not None
            and self.chapter_end is not None
            and self.chapter_end < self.chapter_start
        ):
            raise ValueError("章节范围无效")
        return self


class WritingPatternConflict(BaseModel):
    conflict_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    dimension: CraftPatternDimension
    applicable_stage: WritingPatternStage
    entry_keys: list[str] = Field(min_length=2, max_length=2)
    reason: Literal["preserve_vs_avoid", "competing_preserve_rules"]


class ModelSafeWritingPatternRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dimension: CraftPatternDimension
    name: str = Field(min_length=1, max_length=120)
    transferable_rule: str = Field(min_length=1, max_length=1000)
    adaptation_risk: str = Field(min_length=1, max_length=600)
    purpose: WritingPatternPurpose
    strategy: WritingPatternStrategy
    weight_basis_points: int = Field(ge=1, le=10_000)
    applicable_stages: list[WritingPatternStage] = Field(min_length=1, max_length=7)
    chapter_start: int | None = Field(default=None, ge=1, le=100_000)
    chapter_end: int | None = Field(default=None, ge=1, le=100_000)


class ModelSafeWritingPatternProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    compiler_version: str = Field(min_length=1, max_length=80)
    topic_revision: int = Field(gt=0)
    topic_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    recipe_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    safety_basis: WritingPatternSafetyBasis
    rules: list[ModelSafeWritingPatternRule] = Field(min_length=1, max_length=500)


class AppliedWritingPatternConflictDecision(WritingPatternConflictDecisionInput):
    affected_entry_keys: list[str] = Field(min_length=2, max_length=2)


class CompiledWritingPatternProfile(BaseModel):
    model_safe_profile: ModelSafeWritingPatternProfile
    conflicts: list[WritingPatternConflict]
    decisions: list[AppliedWritingPatternConflictDecision]
    excluded_entry_keys: list[str]
    profile_fingerprint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PreviewWritingPatternRecipeRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    expected_topic_revision: int = Field(gt=0)
    entries: list[WritingPatternRecipeEntryInput] = Field(min_length=1, max_length=500)
    conflict_decisions: list[WritingPatternConflictDecisionInput] = Field(
        default_factory=list,
        max_length=500,
    )

    @field_validator("name", "description")
    @classmethod
    def reject_recipe_null_bytes(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("写作配方文本不能包含空字节")
        return value

    @model_validator(mode="after")
    def validate_unique_recipe_inputs(self) -> PreviewWritingPatternRecipeRequest:
        entry_keys = [
            (
                entry.asset_version_id,
                entry.dimension,
                entry.pattern_name,
                tuple(entry.applicable_stages),
                entry.chapter_start,
                entry.chapter_end,
            )
            for entry in self.entries
        ]
        if len(entry_keys) != len(set(entry_keys)):
            raise ValueError("写作配方条目不能重复")
        decision_keys = [decision.conflict_key for decision in self.conflict_decisions]
        if len(decision_keys) != len(set(decision_keys)):
            raise ValueError("冲突决定不能重复")
        return self


class CreateWritingPatternRecipeRequest(PreviewWritingPatternRecipeRequest):
    expected_preview_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PreviewWritingPatternRecipeVersionRequest(PreviewWritingPatternRecipeRequest):
    expected_latest_version: int = Field(ge=1)


class CreateWritingPatternRecipeVersionRequest(
    PreviewWritingPatternRecipeVersionRequest
):
    expected_preview_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class WritingPatternRecipePreview(BaseModel):
    name: str
    description: str
    expected_topic_revision: int = Field(gt=0)
    expected_latest_version: int | None = Field(default=None, ge=1)
    sources: list[RecipeSourceSnapshot] = Field(min_length=1, max_length=500)
    conflicts: list[WritingPatternConflict]
    decisions: list[WritingPatternConflictDecisionInput]
    unresolved_conflict_count: int = Field(ge=0)
    source_asset_count: int = Field(ge=1)
    source_work_count: int = Field(ge=1, le=5)
    safety_basis: WritingPatternSafetyBasis
    source_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    recipe_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    preview_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class WritingPatternRecipeVersionSummary(BaseModel):
    id: str
    recipe_id: str
    version: int = Field(ge=1)
    name: str
    description: str
    source_asset_count: int = Field(ge=1)
    source_work_count: int = Field(ge=1, le=5)
    safety_basis: WritingPatternSafetyBasis
    source_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: str


class WritingPatternRecipeVersion(WritingPatternRecipeVersionSummary):
    sources: list[RecipeSourceSnapshot] = Field(min_length=1, max_length=500)
    conflicts: list[WritingPatternConflict]
    conflict_decisions: list[WritingPatternConflictDecisionInput]


class WritingPatternRecipeSummary(BaseModel):
    id: str
    lifecycle_state: WritingPatternLifecycleState
    lifecycle_revision: int = Field(ge=0)
    latest_version: WritingPatternRecipeVersionSummary
    created_at: str
    updated_at: str


class WritingPatternRecipePage(BaseModel):
    items: list[WritingPatternRecipeSummary]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class WritingPatternRecipeSeries(BaseModel):
    id: str
    lifecycle_state: WritingPatternLifecycleState
    lifecycle_revision: int = Field(ge=0)
    versions: list[WritingPatternRecipeVersionSummary] = Field(min_length=1)
    created_at: str
    updated_at: str


class PreviewWritingPatternReuseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_recipe_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_topic_revision: int = Field(gt=0)


class ReuseWritingPatternRecipeRequest(PreviewWritingPatternReuseRequest):
    expected_preview_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class WritingPatternProfilePreview(BaseModel):
    recipe_version_id: str
    recipe_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    topic_decision_version_id: str
    topic_revision: int = Field(gt=0)
    topic_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    safety_basis: WritingPatternSafetyBasis
    model_safe_profile: ModelSafeWritingPatternProfile
    conflicts: list[WritingPatternConflict]
    decisions: list[AppliedWritingPatternConflictDecision]
    excluded_entry_keys: list[str]
    source_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile_fingerprint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    preview_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class WritingPatternProfileSummary(BaseModel):
    id: str
    project_id: str
    recipe_version_id: str
    recipe_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    topic_revision: int = Field(gt=0)
    topic_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    safety_basis: WritingPatternSafetyBasis
    profile_fingerprint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    lifecycle_state: WritingPatternLifecycleState
    lifecycle_revision: int = Field(ge=0)
    is_current: bool
    created_at: str
    updated_at: str


class WritingPatternProfileVersion(WritingPatternProfileSummary):
    topic_decision_version_id: str
    compiler_version: str
    source_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_safe_profile: ModelSafeWritingPatternProfile
    conflicts: list[WritingPatternConflict]
    decisions: list[AppliedWritingPatternConflictDecision]
    excluded_entry_keys: list[str]


class UpdateWritingPatternLifecycleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: WritingPatternLifecycleState
    expected_lifecycle_revision: int = Field(ge=0)
