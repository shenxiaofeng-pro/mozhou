from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
from threading import Barrier
from uuid import uuid4

from fastapi.testclient import TestClient

from app.archive import canonical_json
from app.craft_patterns import CraftPatternRepository
from app.database import Database
from app.main import create_app
from app.models import (
    CraftPatternAsset,
    CraftPatternAssetType,
    CraftPatternDimension,
    CraftPatternEvidence,
    CraftPatternItem,
    CraftPatternMaterial,
    ImportReferenceWorkRequest,
    ReferenceRightsBasis,
)
from app.repository import ProjectRepository
from app.writing_patterns.models import (
    PreviewWritingPatternRecipeVersionRequest,
    PreviewWritingPatternReuseRequest,
)
from app.writing_patterns.repository import WritingPatternError


def _digest(label: str) -> str:
    return sha256(label.encode()).hexdigest()


def _create_confirmed_project(client: TestClient, title: str = "编译配方项目") -> str:
    created = client.post(
        "/api/projects",
        json={
            "title": title,
            "genre": "urban_rebirth",
            "rebirth_year": 1998,
            "rebirth_location": "福建南平",
            "template_id": "urban-rebirth",
            "topic_seed": "主角回到九八年，从挽救家庭工厂开始。",
        },
    )
    assert created.status_code == 201, created.text
    project_id = created.json()["project"]["id"]
    confirmed = client.post(
        f"/api/projects/{project_id}/topic-decision/confirm",
        json={"expected_revision": 0},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["confirmed_revision"] == 1
    return project_id


def _materialize_stage(
    database: Database,
    project_id: str,
    marker: str,
    *,
    with_raw_source: bool = True,
    leak_source_title: bool = False,
    work_title_override: str | None = None,
) -> CraftPatternAsset:
    repository = ProjectRepository(database)
    if with_raw_source:
        content = f"{marker}独特开篇证据" + "故事节奏" * 100
        work = repository.import_reference_work(
            project_id,
            ImportReferenceWorkRequest(
                title=work_title_override or f"作者自有作品 {marker}",
                source_filename=f"{marker}.txt",
                rights_basis=ReferenceRightsBasis.SELF_OWNED,
                segment_target_characters=100_000,
                content=content,
            ),
        )
        segment = work.segments[0]
        work_id = work.id
        segment_id = segment.id
        work_title = work.title
        excerpt = content[:12]
        absolute_start = segment.start_char
    else:
        work_id = str(uuid4())
        segment_id = str(uuid4())
        work_title = f"已净化来源 {marker}"
        excerpt = f"{marker}-abstract"
        absolute_start = 0
    evidence = CraftPatternEvidence(
        id=str(uuid4()),
        work_id=work_id,
        work_title=work_title,
        segment_id=segment_id,
        stage_label="第 1 阶段",
        chapter_label=None,
        absolute_start_char=absolute_start,
        absolute_end_char=absolute_start + len(excerpt),
        evidence_summary="只保留功能性证据摘要",
        evidence_sha256=sha256(excerpt.encode()).hexdigest(),
        confidence=0.9,
    )
    material = CraftPatternMaterial(
        title=f"阶段卡 {marker}",
        summary=f"{marker} 的抽象写作规律",
        craft_items=[
            CraftPatternItem(
                dimension=dimension,
                name=f"{marker}-{dimension.value}",
                observation=f"{marker} observation must stay outside profile",
                transferable_rule=(
                    f"应当照搬《{work_title}》的具体写法"
                    if leak_source_title
                    and dimension == CraftPatternDimension.HOOK_MECHANICS
                    else f"{marker} 仅迁移 {dimension.value} 的功能"
                ),
                adaptation_risk=f"{marker} 需重构人物与场景",
                evidence=[evidence],
            )
            for dimension in CraftPatternDimension
        ],
    )
    return CraftPatternRepository(database).materialize_and_link(
        project_id=project_id,
        asset_type=CraftPatternAssetType.STAGE,
        generation_fingerprint_sha256=_digest(f"generation:{marker}"),
        source_fingerprint_sha256=_digest(f"source:{marker}"),
        source_job_id=None,
        output_ordinal=0,
        source_work_ids=[work_id],
        source_segment_ids=[segment_id],
        source_asset_version_ids=[],
        material=material,
        author_focus="",
        provider="test",
        provider_profile_id=None,
        profile_revision=None,
        model="recipe-fixture",
    )


def _entry(
    asset: CraftPatternAsset,
    marker: str,
    *,
    dimension: str = "hook_mechanics",
    strategy: str = "transform",
    weight: int = 60,
) -> dict[str, object]:
    return {
        "asset_version_id": asset.id,
        "asset_content_sha256": asset.content_sha256,
        "dimension": dimension,
        "pattern_name": f"{marker}-{dimension}",
        "purpose": "learn",
        "strategy": strategy,
        "weight": weight,
        "applicable_stages": ["chapter_brief", "chapter_draft"],
        "chapter_start": 1,
        "chapter_end": 30,
        "note": "用于前三十章，但不复刻人物。",
    }


def _materialize_fusion(
    database: Database,
    project_id: str,
    left: CraftPatternAsset,
    right: CraftPatternAsset,
    marker: str,
) -> CraftPatternAsset:
    left_by_dimension = {item.dimension: item for item in left.craft_items}
    right_by_dimension = {item.dimension: item for item in right.craft_items}
    material = CraftPatternMaterial(
        title=f"融合模式 {marker}",
        summary="来源标题和证据均不会进入作者配方画像。",
        craft_items=[
            CraftPatternItem(
                dimension=dimension,
                name=f"{marker}-{dimension.value}",
                observation="只记录多作品共同的抽象观察。",
                transferable_rule=f"仅迁移 {dimension.value} 的叙事功能",
                adaptation_risk="必须替换人物、场景与具体表达。",
                evidence=(
                    [left_by_dimension[dimension].evidence[0]]
                    if dimension == CraftPatternDimension.HOOK_MECHANICS
                    else [
                        left_by_dimension[dimension].evidence[0],
                        right_by_dimension[dimension].evidence[0],
                    ]
                ),
            )
            for dimension in CraftPatternDimension
        ],
    )
    return CraftPatternRepository(database).materialize_and_link(
        project_id=project_id,
        asset_type=CraftPatternAssetType.FUSION_MATERIAL,
        generation_fingerprint_sha256=_digest(f"generation:{marker}"),
        source_fingerprint_sha256=_digest(f"source:{marker}"),
        source_job_id=None,
        output_ordinal=0,
        source_work_ids=[*left.source_work_ids, *right.source_work_ids],
        source_segment_ids=[*left.source_segment_ids, *right.source_segment_ids],
        source_asset_version_ids=[left.id, right.id],
        material=material,
        author_focus="",
        provider="test",
        provider_profile_id=None,
        profile_revision=None,
        model="recipe-fixture",
    )


def _create_recipe(
    client: TestClient,
    project_id: str,
    asset: CraftPatternAsset,
    marker: str,
    *,
    strategy: str = "transform",
) -> dict[str, object]:
    draft = {
        "name": f"{marker} 配方",
        "description": "只保留可迁移的功能性规律。",
        "expected_topic_revision": 1,
        "entries": [_entry(asset, marker, strategy=strategy)],
        "conflict_decisions": [],
    }
    preview = client.post(
        f"/api/projects/{project_id}/writing-pattern-recipes/preview",
        json=draft,
    )
    assert preview.status_code == 200, preview.text
    created = client.post(
        f"/api/projects/{project_id}/writing-pattern-recipes",
        json={**draft, "expected_preview_sha256": preview.json()["preview_sha256"]},
    )
    assert created.status_code == 201, created.text
    return created.json()


def test_recipe_to_active_profile_is_versioned_safe_and_cas_guarded(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "writing-pattern.db"
    database = Database(database_path)
    with TestClient(create_app(database_path, defer_job_runtime=True)) as client:
        project_id = _create_confirmed_project(client)
        asset = _materialize_stage(database, project_id, "alpha")
        draft = {
            "name": "开篇紧迫感配方",
            "description": "保留功能，重构人物与具体场景。",
            "expected_topic_revision": 1,
            "entries": [_entry(asset, "alpha")],
            "conflict_decisions": [],
        }

        preview = client.post(
            f"/api/projects/{project_id}/writing-pattern-recipes/preview",
            json=draft,
        )
        assert preview.status_code == 200, preview.text
        preview_json = preview.json()
        assert preview_json["source_work_count"] == 1
        assert preview_json["safety_basis"] == "source_verified"
        assert preview_json["unresolved_conflict_count"] == 0
        with database.connect() as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM writing_pattern_recipes"
            ).fetchone()[0] == 0

        created = client.post(
            f"/api/projects/{project_id}/writing-pattern-recipes",
            json={**draft, "expected_preview_sha256": preview_json["preview_sha256"]},
        )
        assert created.status_code == 201, created.text
        version = created.json()
        assert version["version"] == 1
        assert version["sources"][0]["asset_version_id"] == asset.id
        assert version["sources"][0]["asset_content_sha256"] == asset.content_sha256

        global_page = client.get("/api/writing-pattern-recipes").json()
        assert global_page["total"] == 1
        assert "sources" not in global_page["items"][0]
        recipe_id = version["recipe_id"]
        series = client.get(f"/api/writing-pattern-recipes/{recipe_id}")
        assert series.status_code == 200
        assert [item["version"] for item in series.json()["versions"]] == [1]
        detail = client.get(f"/api/writing-pattern-recipe-versions/{version['id']}")
        assert detail.status_code == 200
        assert detail.json()["content_sha256"] == version["content_sha256"]

        reuse_body = {
            "expected_recipe_content_sha256": version["content_sha256"],
            "expected_topic_revision": 1,
        }
        profile_preview = client.post(
            f"/api/projects/{project_id}/writing-pattern-recipes/{version['id']}/reuse-preview",
            json=reuse_body,
        )
        assert profile_preview.status_code == 200, profile_preview.text
        safe_payload = profile_preview.json()["model_safe_profile"]
        encoded = str(safe_payload)
        assert "asset_version_id" not in encoded
        assert "work_id" not in encoded
        assert "work_title" not in encoded
        assert "observation" not in encoded
        assert "evidence" not in encoded

        activated = client.post(
            f"/api/projects/{project_id}/writing-pattern-recipes/{version['id']}/reuse",
            json={
                **reuse_body,
                "expected_preview_sha256": profile_preview.json()["preview_sha256"],
            },
        )
        assert activated.status_code == 201, activated.text
        profile = activated.json()
        assert profile["lifecycle_state"] == "active"
        assert profile["lifecycle_revision"] == 0
        assert profile["profile_fingerprint_sha256"] == profile_preview.json()[
            "profile_fingerprint_sha256"
        ]
        repeated = client.post(
            f"/api/projects/{project_id}/writing-pattern-recipes/{version['id']}/reuse",
            json={
                **reuse_body,
                "expected_preview_sha256": profile_preview.json()["preview_sha256"],
            },
        )
        assert repeated.status_code == 200
        assert repeated.json()["id"] == profile["id"]
        current = client.get(f"/api/projects/{project_id}/writing-pattern-profile")
        assert current.status_code == 200
        assert current.json()["id"] == profile["id"]

        archived = client.patch(
            f"/api/projects/{project_id}/writing-pattern-profiles/{profile['id']}/lifecycle",
            json={"state": "archived", "expected_lifecycle_revision": 0},
        )
        assert archived.status_code == 200
        assert archived.json()["lifecycle_revision"] == 1
        stale = client.patch(
            f"/api/projects/{project_id}/writing-pattern-profiles/{profile['id']}/lifecycle",
            json={"state": "active", "expected_lifecycle_revision": 0},
        )
        assert stale.status_code == 409
        restored = client.patch(
            f"/api/projects/{project_id}/writing-pattern-profiles/{profile['id']}/lifecycle",
            json={"state": "active", "expected_lifecycle_revision": 1},
        )
        assert restored.status_code == 200
        assert restored.json()["lifecycle_revision"] == 2

        recipe_archived = client.patch(
            f"/api/writing-pattern-recipes/{recipe_id}/lifecycle",
            json={"state": "archived", "expected_lifecycle_revision": 0},
        )
        assert recipe_archived.status_code == 200
        assert recipe_archived.json()["lifecycle_state"] == "archived"
        assert client.get(f"/api/projects/{project_id}/writing-pattern-profile").status_code == 200

    with database.connect() as connection:
        persisted_profile = connection.execute(
            "SELECT profile_json FROM writing_pattern_profile_versions"
        ).fetchone()[0]
    assert "observation" not in persisted_profile
    assert "evidence" not in persisted_profile
    assert "作者自有作品" not in persisted_profile


def test_recipe_conflicts_are_previewed_and_must_be_resolved_before_create(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "recipe-conflict.db"
    database = Database(database_path)
    with TestClient(create_app(database_path, defer_job_runtime=True)) as client:
        project_id = _create_confirmed_project(client, "冲突配方")
        left = _materialize_stage(database, project_id, "left")
        right = _materialize_stage(database, project_id, "right")
        entries = [
            _entry(left, "left", strategy="preserve_function"),
            _entry(right, "right", strategy="preserve_function"),
        ]
        draft = {
            "name": "需要裁决的开篇配方",
            "description": "两个硬约束不能静默平均。",
            "expected_topic_revision": 1,
            "entries": entries,
            "conflict_decisions": [],
        }
        preview = client.post(
            f"/api/projects/{project_id}/writing-pattern-recipes/preview",
            json=draft,
        )
        assert preview.status_code == 200, preview.text
        value = preview.json()
        assert value["unresolved_conflict_count"] == 2
        blocked = client.post(
            f"/api/projects/{project_id}/writing-pattern-recipes",
            json={**draft, "expected_preview_sha256": value["preview_sha256"]},
        )
        assert blocked.status_code == 409
        assert blocked.json()["detail"]["code"] == "unresolved_recipe_conflict"
        with database.connect() as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM writing_pattern_recipes"
            ).fetchone()[0] == 0

        chosen_key = next(
            source["entry_key"]
            for source in value["sources"]
            if source["asset_version_id"] == left.id
        )
        decisions = [
            {
                "conflict_key": conflict["conflict_key"],
                "resolution": "choose_source",
                "chosen_entry_key": chosen_key,
            }
            for conflict in value["conflicts"]
        ]
        resolved_draft = {**draft, "conflict_decisions": decisions}
        resolved = client.post(
            f"/api/projects/{project_id}/writing-pattern-recipes/preview",
            json=resolved_draft,
        )
        reversed_preview = client.post(
            f"/api/projects/{project_id}/writing-pattern-recipes/preview",
            json={**resolved_draft, "entries": list(reversed(entries))},
        )
        assert resolved.status_code == reversed_preview.status_code == 200
        assert resolved.json()["preview_sha256"] == reversed_preview.json()[
            "preview_sha256"
        ]
        created = client.post(
            f"/api/projects/{project_id}/writing-pattern-recipes",
            json={
                **resolved_draft,
                "expected_preview_sha256": resolved.json()["preview_sha256"],
            },
        )
        assert created.status_code == 201, created.text
        assert len(created.json()["conflict_decisions"]) == 2


def test_new_recipe_version_is_immutable_and_latest_version_is_cas_guarded(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "recipe-version.db"
    database = Database(database_path)
    with TestClient(create_app(database_path, defer_job_runtime=True)) as client:
        project_id = _create_confirmed_project(client, "配方版本")
        asset = _materialize_stage(database, project_id, "versioned")
        first = _create_recipe(client, project_id, asset, "versioned")
        recipe_id = first["recipe_id"]
        version_draft = {
            "name": "versioned 配方 v2",
            "description": "第二版只改作者配方参数。",
            "expected_topic_revision": 1,
            "expected_latest_version": 1,
            "entries": [_entry(asset, "versioned", weight=80)],
            "conflict_decisions": [],
        }
        preview = client.post(
            f"/api/projects/{project_id}/writing-pattern-recipes/{recipe_id}/versions/preview",
            json=version_draft,
        )
        assert preview.status_code == 200, preview.text
        second = client.post(
            f"/api/projects/{project_id}/writing-pattern-recipes/{recipe_id}/versions",
            json={
                **version_draft,
                "expected_preview_sha256": preview.json()["preview_sha256"],
            },
        )
        assert second.status_code == 201, second.text
        assert second.json()["version"] == 2
        assert client.get(
            f"/api/writing-pattern-recipe-versions/{first['id']}"
        ).json()["content_sha256"] == first["content_sha256"]
        stale = client.post(
            f"/api/projects/{project_id}/writing-pattern-recipes/{recipe_id}/versions",
            json={
                **version_draft,
                "expected_preview_sha256": preview.json()["preview_sha256"],
            },
        )
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "recipe_version_changed"
        series = client.get(f"/api/writing-pattern-recipes/{recipe_id}").json()
        assert [item["version"] for item in series["versions"]] == [2, 1]


def test_cross_project_hash_and_topic_changes_fail_without_recipe_side_effects(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "recipe-boundaries.db"
    database = Database(database_path)
    with TestClient(create_app(database_path, defer_job_runtime=True)) as client:
        owner_id = _create_confirmed_project(client, "资产所有者")
        other_id = _create_confirmed_project(client, "其他项目")
        asset = _materialize_stage(database, owner_id, "private")
        draft = {
            "name": "跨项目不可见",
            "description": "",
            "expected_topic_revision": 1,
            "entries": [_entry(asset, "private")],
            "conflict_decisions": [],
        }
        cross_project = client.post(
            f"/api/projects/{other_id}/writing-pattern-recipes/preview",
            json=draft,
        )
        assert cross_project.status_code == 404
        bad_entry = {**_entry(asset, "private"), "asset_content_sha256": "0" * 64}
        bad_hash = client.post(
            f"/api/projects/{owner_id}/writing-pattern-recipes/preview",
            json={**draft, "entries": [bad_entry]},
        )
        assert bad_hash.status_code == 409
        assert bad_hash.json()["detail"]["code"] == "asset_hash_mismatch"

        preview = client.post(
            f"/api/projects/{owner_id}/writing-pattern-recipes/preview",
            json=draft,
        )
        assert preview.status_code == 200
        with database.connect() as connection:
            connection.execute(
                "UPDATE topic_decisions SET revision = revision + 1 WHERE project_id = ?",
                (owner_id,),
            )
        stale_topic = client.post(
            f"/api/projects/{owner_id}/writing-pattern-recipes",
            json={
                **draft,
                "expected_preview_sha256": preview.json()["preview_sha256"],
            },
        )
        assert stale_topic.status_code == 409
        assert stale_topic.json()["detail"]["code"] in {
            "topic_not_confirmed",
            "topic_changed",
        }
    with database.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM writing_pattern_recipes"
        ).fetchone()[0] == 0


def test_recipe_compiles_abstract_only_after_raw_source_is_purged(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "recipe-purged-source.db"
    database = Database(database_path)
    with TestClient(create_app(database_path, defer_job_runtime=True)) as client:
        project_id = _create_confirmed_project(client, "原文删除后复用")
        asset = _materialize_stage(database, project_id, "purged")
        version = _create_recipe(client, project_id, asset, "purged")
        impact = client.get(
            f"/api/reference-library/works/{asset.source_work_ids[0]}/impact"
        )
        assert impact.status_code == 200
        deleted = client.delete(
            f"/api/reference-library/works/{asset.source_work_ids[0]}",
            params={"confirm_purge": "true"},
        )
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["retained_craft_asset_count"] == 1
        preview = client.post(
            f"/api/projects/{project_id}/writing-pattern-recipes/{version['id']}/reuse-preview",
            json={
                "expected_recipe_content_sha256": version["content_sha256"],
                "expected_topic_revision": 1,
            },
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["safety_basis"] == "abstract_only"
        activated = client.post(
            f"/api/projects/{project_id}/writing-pattern-recipes/{version['id']}/reuse",
            json={
                "expected_recipe_content_sha256": version["content_sha256"],
                "expected_topic_revision": 1,
                "expected_preview_sha256": preview.json()["preview_sha256"],
            },
        )
        assert activated.status_code == 201, activated.text
        assert activated.json()["model_safe_profile"]["safety_basis"] == "abstract_only"


def test_project_allows_only_one_active_profile_and_stale_profile_cannot_restore(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "one-active-profile.db"
    database = Database(database_path)
    with TestClient(create_app(database_path, defer_job_runtime=True)) as client:
        project_id = _create_confirmed_project(client, "单一激活写作模式")
        first_asset = _materialize_stage(database, project_id, "first-profile")
        second_asset = _materialize_stage(database, project_id, "second-profile")
        first_recipe = _create_recipe(client, project_id, first_asset, "first-profile")
        second_recipe = _create_recipe(client, project_id, second_asset, "second-profile")

        def activate(recipe: dict[str, object]) -> dict[str, object]:
            body = {
                "expected_recipe_content_sha256": recipe["content_sha256"],
                "expected_topic_revision": 1,
            }
            preview = client.post(
                f"/api/projects/{project_id}/writing-pattern-recipes/{recipe['id']}/reuse-preview",
                json=body,
            )
            assert preview.status_code == 200, preview.text
            response = client.post(
                f"/api/projects/{project_id}/writing-pattern-recipes/{recipe['id']}/reuse",
                json={**body, "expected_preview_sha256": preview.json()["preview_sha256"]},
            )
            return {"response": response, "preview": preview.json()}

        first_result = activate(first_recipe)
        assert first_result["response"].status_code == 201
        first_profile = first_result["response"].json()
        blocked = activate(second_recipe)["response"]
        assert blocked.status_code == 409
        assert blocked.json()["detail"]["code"] == "active_profile_exists"
        with database.connect() as connection:
            assert connection.execute(
                """
                SELECT COUNT(*) FROM project_writing_pattern_profiles
                WHERE project_id = ? AND lifecycle_state = 'active'
                """,
                (project_id,),
            ).fetchone()[0] == 1

        listed = client.get(f"/api/projects/{project_id}/writing-pattern-profiles")
        assert listed.status_code == 200, listed.text
        assert listed.json()[0]["is_current"] is True
        archived_first = client.patch(
            f"/api/projects/{project_id}/writing-pattern-profiles/{first_profile['id']}/lifecycle",
            json={"state": "archived", "expected_lifecycle_revision": 0},
        )
        assert archived_first.status_code == 200
        second_result = activate(second_recipe)
        assert second_result["response"].status_code == 201
        second_profile = second_result["response"].json()
        archived_second = client.patch(
            f"/api/projects/{project_id}/writing-pattern-profiles/{second_profile['id']}/lifecycle",
            json={"state": "archived", "expected_lifecycle_revision": 0},
        )
        assert archived_second.status_code == 200
        with database.connect() as connection:
            connection.execute(
                "UPDATE topic_decisions SET revision = revision + 1 WHERE project_id = ?",
                (project_id,),
            )
        stale_restore = client.patch(
            f"/api/projects/{project_id}/writing-pattern-profiles/{second_profile['id']}/lifecycle",
            json={"state": "active", "expected_lifecycle_revision": 1},
        )
        assert stale_restore.status_code == 409
        assert stale_restore.json()["detail"]["code"] == "profile_stale"


def test_recipe_rejects_more_than_five_distinct_works_without_writes(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "five-work-limit.db"
    database = Database(database_path)
    with TestClient(create_app(database_path, defer_job_runtime=True)) as client:
        project_id = _create_confirmed_project(client, "五本来源上限")
        entries = [
            _entry(
                _materialize_stage(database, project_id, f"work-{index}"),
                f"work-{index}",
                dimension="hook_mechanics",
            )
            for index in range(6)
        ]
        response = client.post(
            f"/api/projects/{project_id}/writing-pattern-recipes/preview",
            json={
                "name": "超出来源上限",
                "description": "",
                "expected_topic_revision": 1,
                "entries": entries,
                "conflict_decisions": [],
            },
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "one_to_five_works_required"
    with database.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM writing_pattern_recipes"
        ).fetchone()[0] == 0


def test_recipe_preview_rejects_archived_source_and_invalid_entry_shape(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "recipe-input-validation.db"
    database = Database(database_path)
    with TestClient(create_app(database_path, defer_job_runtime=True)) as client:
        project_id = _create_confirmed_project(client, "配方输入校验")
        asset = _materialize_stage(database, project_id, "archived-source")
        draft = {
            "name": "输入校验",
            "description": "",
            "expected_topic_revision": 1,
            "entries": [_entry(asset, "archived-source")],
            "conflict_decisions": [],
        }
        invalid_range = {
            **draft,
            "entries": [{**draft["entries"][0], "chapter_start": 20, "chapter_end": 10}],
        }
        assert client.post(
            f"/api/projects/{project_id}/writing-pattern-recipes/preview",
            json=invalid_range,
        ).status_code == 422
        duplicated = {**draft, "entries": [draft["entries"][0], draft["entries"][0]]}
        assert client.post(
            f"/api/projects/{project_id}/writing-pattern-recipes/preview",
            json=duplicated,
        ).status_code == 422
        counterexample_preserve = {
            **draft,
            "entries": [
                {
                    **draft["entries"][0],
                    "purpose": "counterexample",
                    "strategy": "preserve_function",
                }
            ],
        }
        assert client.post(
            f"/api/projects/{project_id}/writing-pattern-recipes/preview",
            json=counterexample_preserve,
        ).status_code == 422
        leaky_asset = _materialize_stage(
            database,
            project_id,
            "title-leak",
            leak_source_title=True,
        )
        leaky = client.post(
            f"/api/projects/{project_id}/writing-pattern-recipes/preview",
            json={
                **draft,
                "entries": [_entry(leaky_asset, "title-leak")],
            },
        )
        assert leaky.status_code == 400
        assert leaky.json()["detail"]["code"] == "source_title_leak"
        short_title_leak = _materialize_stage(
            database,
            project_id,
            "short-title-leak",
            leak_source_title=True,
            work_title_override="剑来",
        )
        short_leaky = client.post(
            f"/api/projects/{project_id}/writing-pattern-recipes/preview",
            json={
                **draft,
                "entries": [_entry(short_title_leak, "short-title-leak")],
            },
        )
        assert short_leaky.status_code == 400
        assert short_leaky.json()["detail"]["code"] == "source_title_leak"
        archived = client.patch(
            f"/api/projects/{project_id}/reference-craft-assets/{asset.id}/lifecycle",
            json={"state": "archived", "expected_lifecycle_revision": 0},
        )
        assert archived.status_code == 200
        blocked = client.post(
            f"/api/projects/{project_id}/writing-pattern-recipes/preview",
            json=draft,
        )
        assert blocked.status_code == 400
        assert blocked.json()["detail"]["code"] == "source_asset_not_active"


def test_fusion_recipe_counts_only_works_evidenced_by_selected_pattern(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "selected-item-lineage.db"
    database = Database(database_path)
    with TestClient(create_app(database_path, defer_job_runtime=True)) as client:
        project_id = _create_confirmed_project(client, "按技法证据统计来源")
        left = _materialize_stage(database, project_id, "fusion-left")
        right = _materialize_stage(database, project_id, "fusion-right")
        fusion = _materialize_fusion(database, project_id, left, right, "fusion")
        response = client.post(
            f"/api/projects/{project_id}/writing-pattern-recipes/preview",
            json={
                "name": "单条融合技法配方",
                "description": "这条技法只引用左侧作品证据。",
                "expected_topic_revision": 1,
                "entries": [_entry(fusion, "fusion")],
                "conflict_decisions": [],
            },
        )
        assert response.status_code == 200, response.text
        value = response.json()
        assert len(fusion.source_work_ids) == 2
        assert value["source_work_count"] == 1
        assert len(value["sources"][0]["source_work_fingerprints"]) == 1


def test_global_recipe_and_active_profile_round_trip_without_raw_source(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "writing-pattern-archive.db"
    database = Database(database_path)
    with TestClient(create_app(database_path, defer_job_runtime=True)) as client:
        owner_id = _create_confirmed_project(client, "全局配方来源项目")
        target_id = _create_confirmed_project(client, "复用配方项目")
        asset = _materialize_stage(database, owner_id, "archive")
        recipe = _create_recipe(client, owner_id, asset, "archive")
        reuse_body = {
            "expected_recipe_content_sha256": recipe["content_sha256"],
            "expected_topic_revision": 1,
        }
        preview = client.post(
            f"/api/projects/{target_id}/writing-pattern-recipes/{recipe['id']}/reuse-preview",
            json=reuse_body,
        )
        assert preview.status_code == 200, preview.text
        activated = client.post(
            f"/api/projects/{target_id}/writing-pattern-recipes/{recipe['id']}/reuse",
            json={**reuse_body, "expected_preview_sha256": preview.json()["preview_sha256"]},
        )
        assert activated.status_code == 201, activated.text

        exported = client.get(f"/api/projects/{target_id}/export")
        assert exported.status_code == 200, exported.text
        archive = exported.json()
        assert archive["format_version"] == 14
        assert archive["tables"]["reference_works"] == []
        assert len(archive["tables"]["craft_pattern_assets"]) == 1
        assert len(archive["tables"]["writing_pattern_recipes"]) == 1
        assert archive["tables"]["writing_pattern_recipes"][0][
            "created_from_project_id"
        ] is None
        assert len(archive["tables"]["writing_pattern_recipe_versions"]) == 1
        assert len(archive["tables"]["writing_pattern_recipe_sources"]) == 1
        assert len(archive["tables"]["writing_pattern_profile_versions"]) == 1
        restored = client.post(
            "/api/project-imports",
            content=canonical_json(archive),
            headers={"Content-Type": "application/json"},
        )
        assert restored.status_code == 201, restored.text
        restored_id = restored.json()["project"]["id"]
        restored_profile = client.get(
            f"/api/projects/{restored_id}/writing-pattern-profile"
        )
        assert restored_profile.status_code == 200, restored_profile.text
        restored_value = restored_profile.json()
        assert restored_value["model_safe_profile"] == activated.json()[
            "model_safe_profile"
        ]
        assert restored_value["profile_fingerprint_sha256"] == activated.json()[
            "profile_fingerprint_sha256"
        ]
        restored_recipe = client.get(
            f"/api/writing-pattern-recipe-versions/{restored_value['recipe_version_id']}"
        )
        assert restored_recipe.status_code == 200, restored_recipe.text
        assert restored_recipe.json()["sources"][0]["asset_content_sha256"] == (
            asset.content_sha256
        )


def test_concurrent_version_and_profile_writes_have_stable_domain_results(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "writing-pattern-concurrency.db"
    database = Database(database_path)
    application = create_app(database_path, defer_job_runtime=True)
    with TestClient(application) as client:
        project_id = _create_confirmed_project(client, "配方并发保护")
        asset = _materialize_stage(database, project_id, "concurrent")
        first = _create_recipe(client, project_id, asset, "concurrent")
        service = application.state.writing_pattern_service
        version_request = PreviewWritingPatternRecipeVersionRequest(
            name="并发第二版",
            description="两个窗口同时保存，只允许一个版本成功。",
            expected_topic_revision=1,
            expected_latest_version=1,
            entries=[_entry(asset, "concurrent", weight=75)],
            conflict_decisions=[],
        )
        version_preview = service.preview_recipe_version(
            project_id,
            str(first["recipe_id"]),
            version_request,
        )
        version_barrier = Barrier(2)

        def persist_version() -> str:
            version_barrier.wait()
            try:
                service.repository.persist_recipe_version(
                    project_id,
                    version_preview,
                    recipe_id=str(first["recipe_id"]),
                    expected_latest_version=1,
                )
            except WritingPatternError as error:
                return str(error)
            return "created"

        with ThreadPoolExecutor(max_workers=2) as executor:
            version_results = list(executor.map(lambda _index: persist_version(), range(2)))
        assert sorted(version_results) == ["created", "recipe_version_changed"]

        profile_preview = service.preview_reuse(
            project_id,
            str(first["id"]),
            PreviewWritingPatternReuseRequest(
                expected_recipe_content_sha256=str(first["content_sha256"]),
                expected_topic_revision=1,
            ),
        )
        profile_barrier = Barrier(2)

        def persist_profile() -> tuple[str, bool]:
            profile_barrier.wait()
            profile, created = service.repository.persist_profile(
                project_id,
                profile_preview,
            )
            return profile.id, created

        with ThreadPoolExecutor(max_workers=2) as executor:
            profile_results = list(executor.map(lambda _index: persist_profile(), range(2)))
        assert len({profile_id for profile_id, _created in profile_results}) == 1
        assert sorted(created for _profile_id, created in profile_results) == [False, True]
        with database.connect() as connection:
            assert connection.execute(
                """
                SELECT COUNT(*) FROM project_writing_pattern_profiles
                WHERE project_id = ? AND lifecycle_state = 'active'
                """,
                (project_id,),
            ).fetchone()[0] == 1


def test_raw_inclusive_archive_rebinds_recipe_and_profile_hash_closure(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "writing-pattern-raw-archive.db"
    database = Database(database_path)
    with TestClient(create_app(database_path, defer_job_runtime=True)) as client:
        project_id = _create_confirmed_project(client, "带原文归档闭包")
        asset = _materialize_stage(database, project_id, "raw-archive")
        recipe = _create_recipe(client, project_id, asset, "raw-archive")
        reuse_body = {
            "expected_recipe_content_sha256": recipe["content_sha256"],
            "expected_topic_revision": 1,
        }
        preview = client.post(
            f"/api/projects/{project_id}/writing-pattern-recipes/{recipe['id']}/reuse-preview",
            json=reuse_body,
        ).json()
        activated = client.post(
            f"/api/projects/{project_id}/writing-pattern-recipes/{recipe['id']}/reuse",
            json={**reuse_body, "expected_preview_sha256": preview["preview_sha256"]},
        )
        assert activated.status_code == 201, activated.text
        archive = client.get(
            f"/api/projects/{project_id}/export?include_reference_assets=true"
        ).json()
        assert archive["tables"]["reference_works"]
        restored = client.post(
            "/api/project-imports",
            content=canonical_json(archive),
            headers={"Content-Type": "application/json"},
        )
        assert restored.status_code == 201, restored.text
        restored_id = restored.json()["project"]["id"]
        profile = client.get(
            f"/api/projects/{restored_id}/writing-pattern-profile"
        )
        assert profile.status_code == 200, profile.text
        profile_value = profile.json()
        version = client.get(
            f"/api/writing-pattern-recipe-versions/{profile_value['recipe_version_id']}"
        )
        assert version.status_code == 200, version.text
        version_value = version.json()
        assert profile_value["recipe_content_sha256"] == version_value["content_sha256"]
        assert profile_value["source_snapshot_sha256"] == version_value[
            "source_snapshot_sha256"
        ]
        assert profile_value["model_safe_profile"]["recipe_content_sha256"] == (
            version_value["content_sha256"]
        )
        assert version_value["sources"][0]["asset_version_id"] != asset.id
