from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from app.writing_patterns.models import (
    CreateWritingPatternRecipeRequest,
    CreateWritingPatternRecipeVersionRequest,
    PreviewWritingPatternRecipeRequest,
    PreviewWritingPatternRecipeVersionRequest,
    PreviewWritingPatternReuseRequest,
    ReuseWritingPatternRecipeRequest,
    UpdateWritingPatternLifecycleRequest,
    WritingPatternLifecycleState,
    WritingPatternProfilePreview,
    WritingPatternProfileSummary,
    WritingPatternProfileVersion,
    WritingPatternRecipePage,
    WritingPatternRecipePreview,
    WritingPatternRecipeSeries,
    WritingPatternRecipeVersion,
)
from app.writing_patterns.repository import (
    WritingPatternError,
    WritingPatternNotFoundError,
)
from app.writing_patterns.service import WritingPatternService

writing_pattern_router = APIRouter()


def _service(request: Request) -> WritingPatternService:
    service: WritingPatternService = request.app.state.writing_pattern_service
    return service


def _http_error(error: WritingPatternError) -> HTTPException:
    code = str(error)
    messages = {
        "topic_not_confirmed": "请先确认当前选题",
        "topic_changed": "选题已更新，请重新预览配方",
        "preview_changed": "配方预览条件已变化，请重新预览",
        "recipe_version_changed": "配方已有新版本，请刷新后再编辑",
        "duplicate_recipe_version": "相同内容的配方版本已存在",
        "recipe_archived": "该配方已归档，不能创建新版本或引用",
        "active_profile_exists": "当前项目已有激活的写作模式，请先归档",
        "profile_already_archived": "该写作模式已归档，请使用恢复操作",
        "profile_stale": "选题已更新，该写作模式不能恢复，请重新编译",
        "stale_lifecycle_revision": "状态已更新，请刷新后重试",
        "unresolved_recipe_conflict": "配方仍有未处理的冲突",
        "asset_hash_mismatch": "来源模式版本已变化，请重新选择",
        "one_to_five_works_required": "一份配方必须来自 1–5 本不同作品",
        "multiple_asset_versions_in_family": "同一模式系列不能混用多个版本",
        "pattern_item_not_found": "选中的技法不属于该模式版本",
        "source_title_leak": "该技法仍包含来源作品标题，请先完成抽象化",
        "partial_range_conflict_not_supported": "冲突规则的章节范围不一致，请拆成相同范围后再裁决",
        "unknown_conflict_decision": "冲突决定已过期，请重新预览",
        "chosen_entry_not_in_conflict": "冲突决定的来源无效",
    }
    conflict_codes = {
        "topic_not_confirmed",
        "topic_changed",
        "preview_changed",
        "recipe_version_changed",
        "duplicate_recipe_version",
        "recipe_archived",
        "active_profile_exists",
        "profile_already_archived",
        "profile_stale",
        "stale_lifecycle_revision",
        "unresolved_recipe_conflict",
        "asset_hash_mismatch",
        "unknown_conflict_decision",
        "chosen_entry_not_in_conflict",
        "partial_range_conflict_not_supported",
    }
    return HTTPException(
        status_code=409 if code in conflict_codes else 400,
        detail={
            "code": code,
            "message": messages.get(code, "写作配方请求无效"),
        },
    )


@writing_pattern_router.post(
    "/api/projects/{project_id}/writing-pattern-recipes/preview",
    response_model=WritingPatternRecipePreview,
)
def preview_recipe(
    project_id: UUID,
    body: PreviewWritingPatternRecipeRequest,
    service: Annotated[WritingPatternService, Depends(_service)],
) -> WritingPatternRecipePreview:
    try:
        return service.preview_recipe(str(project_id), body)
    except WritingPatternNotFoundError as error:
        raise HTTPException(status_code=404, detail="项目或写作模式资产不存在") from error
    except WritingPatternError as error:
        raise _http_error(error) from error


@writing_pattern_router.post(
    "/api/projects/{project_id}/writing-pattern-recipes",
    response_model=WritingPatternRecipeVersion,
    status_code=status.HTTP_201_CREATED,
)
def create_recipe(
    project_id: UUID,
    body: CreateWritingPatternRecipeRequest,
    service: Annotated[WritingPatternService, Depends(_service)],
) -> WritingPatternRecipeVersion:
    try:
        return service.create_recipe(str(project_id), body)
    except WritingPatternNotFoundError as error:
        raise HTTPException(status_code=404, detail="项目或写作模式资产不存在") from error
    except WritingPatternError as error:
        raise _http_error(error) from error


@writing_pattern_router.post(
    "/api/projects/{project_id}/writing-pattern-recipes/{recipe_id}/versions/preview",
    response_model=WritingPatternRecipePreview,
)
def preview_recipe_version(
    project_id: UUID,
    recipe_id: UUID,
    body: PreviewWritingPatternRecipeVersionRequest,
    service: Annotated[WritingPatternService, Depends(_service)],
) -> WritingPatternRecipePreview:
    try:
        return service.preview_recipe_version(str(project_id), str(recipe_id), body)
    except WritingPatternNotFoundError as error:
        raise HTTPException(status_code=404, detail="配方或来源资产不存在") from error
    except WritingPatternError as error:
        raise _http_error(error) from error


@writing_pattern_router.post(
    "/api/projects/{project_id}/writing-pattern-recipes/{recipe_id}/versions",
    response_model=WritingPatternRecipeVersion,
    status_code=status.HTTP_201_CREATED,
)
def create_recipe_version(
    project_id: UUID,
    recipe_id: UUID,
    body: CreateWritingPatternRecipeVersionRequest,
    service: Annotated[WritingPatternService, Depends(_service)],
) -> WritingPatternRecipeVersion:
    try:
        return service.create_recipe_version(str(project_id), str(recipe_id), body)
    except WritingPatternNotFoundError as error:
        raise HTTPException(status_code=404, detail="配方或来源资产不存在") from error
    except WritingPatternError as error:
        raise _http_error(error) from error


@writing_pattern_router.get(
    "/api/writing-pattern-recipes",
    response_model=WritingPatternRecipePage,
)
def list_recipes(
    service: Annotated[WritingPatternService, Depends(_service)],
    lifecycle_state: Annotated[WritingPatternLifecycleState | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> WritingPatternRecipePage:
    return service.list_recipes(
        lifecycle_state=lifecycle_state,
        limit=limit,
        offset=offset,
    )


@writing_pattern_router.get(
    "/api/writing-pattern-recipes/{recipe_id}",
    response_model=WritingPatternRecipeSeries,
)
def get_recipe_series(
    recipe_id: UUID,
    service: Annotated[WritingPatternService, Depends(_service)],
) -> WritingPatternRecipeSeries:
    try:
        return service.get_recipe_series(str(recipe_id))
    except WritingPatternNotFoundError as error:
        raise HTTPException(status_code=404, detail="写作配方不存在") from error


@writing_pattern_router.get(
    "/api/writing-pattern-recipe-versions/{version_id}",
    response_model=WritingPatternRecipeVersion,
)
def get_recipe_version(
    version_id: UUID,
    service: Annotated[WritingPatternService, Depends(_service)],
) -> WritingPatternRecipeVersion:
    try:
        return service.get_recipe_version(str(version_id))
    except WritingPatternNotFoundError as error:
        raise HTTPException(status_code=404, detail="写作配方版本不存在") from error
    except WritingPatternError as error:
        raise HTTPException(status_code=409, detail="写作配方版本已损坏") from error


@writing_pattern_router.patch(
    "/api/writing-pattern-recipes/{recipe_id}/lifecycle",
    response_model=WritingPatternRecipeSeries,
)
def update_recipe_lifecycle(
    recipe_id: UUID,
    body: UpdateWritingPatternLifecycleRequest,
    service: Annotated[WritingPatternService, Depends(_service)],
) -> WritingPatternRecipeSeries:
    try:
        return service.update_recipe_lifecycle(str(recipe_id), body)
    except WritingPatternNotFoundError as error:
        raise HTTPException(status_code=404, detail="写作配方不存在") from error
    except WritingPatternError as error:
        raise _http_error(error) from error


@writing_pattern_router.post(
    "/api/projects/{project_id}/writing-pattern-recipes/{version_id}/reuse-preview",
    response_model=WritingPatternProfilePreview,
)
def preview_reuse(
    project_id: UUID,
    version_id: UUID,
    body: PreviewWritingPatternReuseRequest,
    service: Annotated[WritingPatternService, Depends(_service)],
) -> WritingPatternProfilePreview:
    try:
        return service.preview_reuse(str(project_id), str(version_id), body)
    except WritingPatternNotFoundError as error:
        raise HTTPException(status_code=404, detail="项目或写作配方版本不存在") from error
    except WritingPatternError as error:
        raise _http_error(error) from error


@writing_pattern_router.post(
    "/api/projects/{project_id}/writing-pattern-recipes/{version_id}/reuse",
    response_model=WritingPatternProfileVersion,
    status_code=status.HTTP_201_CREATED,
)
def reuse_recipe(
    project_id: UUID,
    version_id: UUID,
    body: ReuseWritingPatternRecipeRequest,
    response: Response,
    service: Annotated[WritingPatternService, Depends(_service)],
) -> WritingPatternProfileVersion:
    try:
        profile, created = service.reuse_recipe(str(project_id), str(version_id), body)
        if not created:
            response.status_code = status.HTTP_200_OK
        return profile
    except WritingPatternNotFoundError as error:
        raise HTTPException(status_code=404, detail="项目或写作配方版本不存在") from error
    except WritingPatternError as error:
        raise _http_error(error) from error


@writing_pattern_router.get(
    "/api/projects/{project_id}/writing-pattern-profiles",
    response_model=list[WritingPatternProfileSummary],
)
def list_profiles(
    project_id: UUID,
    service: Annotated[WritingPatternService, Depends(_service)],
) -> list[WritingPatternProfileSummary]:
    try:
        return service.list_profiles(str(project_id))
    except WritingPatternNotFoundError as error:
        raise HTTPException(status_code=404, detail="项目不存在") from error


@writing_pattern_router.get(
    "/api/projects/{project_id}/writing-pattern-profile",
    response_model=WritingPatternProfileVersion,
)
def get_active_profile(
    project_id: UUID,
    service: Annotated[WritingPatternService, Depends(_service)],
) -> WritingPatternProfileVersion:
    try:
        return service.get_active_profile(str(project_id))
    except WritingPatternNotFoundError as error:
        raise HTTPException(status_code=404, detail="当前没有激活的写作模式") from error
    except WritingPatternError as error:
        raise HTTPException(status_code=409, detail="写作模式快照已损坏") from error


@writing_pattern_router.get(
    "/api/projects/{project_id}/writing-pattern-profiles/{profile_version_id}",
    response_model=WritingPatternProfileVersion,
)
def get_profile(
    project_id: UUID,
    profile_version_id: UUID,
    service: Annotated[WritingPatternService, Depends(_service)],
) -> WritingPatternProfileVersion:
    try:
        return service.get_profile(str(project_id), str(profile_version_id))
    except WritingPatternNotFoundError as error:
        raise HTTPException(status_code=404, detail="写作模式快照不存在") from error
    except WritingPatternError as error:
        raise HTTPException(status_code=409, detail="写作模式快照已损坏") from error


@writing_pattern_router.patch(
    "/api/projects/{project_id}/writing-pattern-profiles/{profile_version_id}/lifecycle",
    response_model=WritingPatternProfileVersion,
)
def update_profile_lifecycle(
    project_id: UUID,
    profile_version_id: UUID,
    body: UpdateWritingPatternLifecycleRequest,
    service: Annotated[WritingPatternService, Depends(_service)],
) -> WritingPatternProfileVersion:
    try:
        return service.update_profile_lifecycle(
            str(project_id),
            str(profile_version_id),
            body,
        )
    except WritingPatternNotFoundError as error:
        raise HTTPException(status_code=404, detail="写作模式快照不存在") from error
    except WritingPatternError as error:
        raise _http_error(error) from error
