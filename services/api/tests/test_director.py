import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.ai import AiGatewayManager
from app.database import Database
from app.main import create_app
from app.models import (
    AiChapterBriefProposal,
    AiProvider,
    AiStatus,
    BookBlueprintField,
    DirectorEntityProposal,
    DirectorExpansionDraft,
    DirectorFieldDraft,
    DirectorSceneBeat,
    DirectorStartupCandidateDraft,
    DirectorStartupDraftSet,
    Genre,
    RollingChapterPlanContent,
    StoryEntityKind,
    VolumePlanContent,
)
from app.providers import (
    AiTaskType,
    CreateModelProfileRequest,
    ModelProfileRepository,
    ProviderKind,
    UpdateAiTaskDefaultRequest,
)


class DirectorGateway:
    def __init__(self, profile_id: str | None = None) -> None:
        self.profile_id = profile_id
        self.startup_calls = 0
        self.expansion_calls = 0
        self.field_calls = 0
        self.brief_calls = 0
        self.draft_calls = 0

    def status(self) -> AiStatus:
        return AiStatus(
            configured=True,
            provider=AiProvider.OPENAI,
            model="director-test-v1",
            key_source="test",
            profile_id=self.profile_id,
            profile_name="导演测试线路" if self.profile_id else None,
        )

    @staticmethod
    def _blueprint_context(context_text: str) -> tuple[Genre, int, str]:
        payload = json.loads(context_text)
        anchor = payload["project_anchor"]
        return Genre(anchor["genre"]), int(anchor["rebirth_year"]), str(anchor["rebirth_location"])

    def propose_director_startup(self, context_text: str) -> DirectorStartupDraftSet:
        self.startup_calls += 1
        payload = json.loads(context_text)
        genre, year, location = self._blueprint_context(context_text)
        candidates = []
        for ordinal in range(1, int(payload["candidate_count"]) + 1):
            candidates.append(
                DirectorStartupCandidateDraft(
                    label=f"方向 {ordinal}",
                    blueprint={
                        "title": f"南平重启线 {ordinal}",
                        "genre": genre,
                        "rebirth_year": year,
                        "rebirth_location": location,
                        "target_audience": "喜欢现实产业升级与强因果回报的男频读者",
                        "core_selling_points": [
                            f"第 {ordinal} 套差异化产业发动机",
                            "真实年代约束下的资源滚雪球",
                        ],
                        "core_desire": f"主角要用第 {ordinal} 条路径弥补家族遗憾",
                        "divergence_point": f"重生当日提前阻止第 {ordinal} 次关键损失",
                        "long_term_promise": "每卷完成一次产业跃迁并改写一段关系",
                        "ending_direction": "完成代际和解并留下可验证的地方产业",
                        "protagonist_arc": "从只想补偿家人走向承担公共责任",
                        "resource_growth": f"从信息差到第 {ordinal} 套组织能力与资本网络",
                        "relationship_design": "家人是价值锚，伙伴负责执行，竞争者迫使升级",
                    },
                    why_distinct=f"冲突发动机采用第 {ordinal} 种资源路径。",
                    risks=["年代资料需由作者继续核实"],
                )
            )
        return DirectorStartupDraftSet(candidates=candidates)

    def expand_book_blueprint(self, context_text: str) -> DirectorExpansionDraft:
        self.expansion_calls += 1
        payload = json.loads(context_text)
        chapter_count = int(payload["chapter_count"])
        return DirectorExpansionDraft(
            entities=[
                DirectorEntityProposal(
                    kind=StoryEntityKind.CHARACTER,
                    name="林川",
                    role="主角与产业执行者",
                    goal="保住家庭并建立可持续事业",
                    initial_state="只有未来记忆，没有现实资源",
                    relationship_notes="与父亲存在未解的信任裂缝",
                ),
                DirectorEntityProposal(
                    kind=StoryEntityKind.RESOURCE,
                    name="旧竹木厂订单网",
                    role="第一卷资源杠杆",
                    goal="验证第一笔可复制现金流",
                    initial_state="关系分散、账期混乱",
                ),
            ],
            volumes=[
                VolumePlanContent(
                    volume_number=1,
                    title="第一卷 抢回第一张订单",
                    direction="用一笔小订单撬动家庭与产业线",
                    central_conflict="主角缺信用，旧厂也不相信年轻人",
                    state_goal="从旁观者变成能调动三方资源的执行者",
                    resource_goal="形成稳定现金流和首批合作关系",
                    emotional_payoff="父亲第一次承认主角能扛事",
                    climax="在违约前夜完成替代交付",
                    verification="订单回款、父子关系和竞争格局同时改变",
                )
            ],
            chapters=[
                RollingChapterPlanContent(
                    chapter_number=number,
                    title=f"第 {number} 章 先抢时间",
                    reader_promise=f"看主角解决第 {number} 个现实阻碍",
                    opening_hook=f"第 {number} 个坏消息提前到来",
                    state_change=f"主角拿到第 {number} 项可验证进展",
                    resource_change=f"资源网络新增第 {number} 个节点",
                    emotional_payoff=f"家人对主角多第 {number} 分信任",
                    ending_cliffhanger=f"更大的第 {number} 项代价浮出水面",
                    verification="有可观察的合同、关系或资源变化",
                    scene_beats=[
                        DirectorSceneBeat(
                            ordinal=1,
                            summary="坏消息落地，迫使主角立即选择",
                            state_change="从被动得知变成主动介入",
                            resource_change="暴露当前资源缺口",
                            emotional_turn="焦虑转为决断",
                            verification="明确下一步行动和失败代价",
                        )
                    ],
                )
                for number in range(1, chapter_count + 1)
            ],
            why_writeable="每章都具有行动、阻力、资源变化和可见兑现。",
            risk_notes=["行业细节需继续绑定现实资料卡"],
        )

    def regenerate_book_field(self, context_text: str) -> DirectorFieldDraft:
        self.field_calls += 1
        target = BookBlueprintField(json.loads(context_text)["target_field"])
        return DirectorFieldDraft(
            target_field=target,
            value="主角要先救下家庭现金流，再证明小城产业也能升级",
            rationale="把抽象补偿欲望改成可连续兑现的双层目标。",
        )

    def propose_brief_from_context(self, context_text: str) -> AiChapterBriefProposal:
        self.brief_calls += 1
        assert "rolling_chapter_plan" in context_text
        return AiChapterBriefProposal(
            title="第一章 坏消息提前三天",
            reader_promise="主角用未来信息抢出第一次行动窗口",
            opening_hook="父亲带回一张即将违约的订单",
            state_change="主角说服父亲给他二十四小时",
            emotional_payoff="父亲第一次没有把他当孩子打发",
            ending_cliffhanger="原本三天后出现的对手已经到了厂门口",
            why_this_works="先给具体损失，再让主角用行动兑现未来优势。",
            risk_notes=[],
        )

    def draft_chapter_from_context(self, context_text: str) -> str:
        self.draft_calls += 1
        assert "坏消息提前三天" in context_text
        return "厂门口的雨落得很密。林川盯着父亲手里的订单，没有立刻说出自己重生的秘密。" * 20


def _project_payload(genre: str = "urban_rebirth") -> dict[str, object]:
    return {
        "title": "回到九八年的南平",
        "genre": genre,
        "rebirth_year": 1998,
        "rebirth_location": "福建南平",
        "chapter_target_words": 3000,
        "safety_buffer_chapters": 3,
    }


def _run_one(client: TestClient) -> None:
    assert client.app.state.job_runtime.run_once() is True


def test_director_candidates_locks_expansion_and_pipeline_never_overwrite_manuscript(
    tmp_path: Path,
) -> None:
    gateway = DirectorGateway()
    app = create_app(
        tmp_path / "director.db",
        AiGatewayManager(gateway),
        defer_job_runtime=True,
    )
    with TestClient(app) as client:
        workspace = client.post("/api/projects", json=_project_payload()).json()
        project_id = workspace["project"]["id"]
        chapter_id = workspace["chapters"][0]["id"]
        startup_request = {
            "idea": "1998 年南平，一个失败商人重生后先救父亲的竹木厂",
            "reality_anchor": "以本地竹木产业和真实订单链为锚",
            "candidate_count": 3,
        }
        preview = client.post(
            f"/api/projects/{project_id}/director/startup-preview",
            json=startup_request,
        )
        assert preview.status_code == 200
        assert preview.json()["estimated_calls"] == 1
        submitted = client.post(
            f"/api/projects/{project_id}/director/startup-jobs",
            json={**startup_request, "confirm_external_processing": True},
        )
        assert submitted.status_code == 202
        startup_job = submitted.json()
        assert startup_job["workflow"] == "director_startup"
        _run_one(client)
        result = client.get(f"/api/jobs/{startup_job['id']}/director-startup-result").json()
        assert len(result["candidates"]) == 3
        chosen = result["candidates"][1]
        selected = client.post(
            f"/api/projects/{project_id}/director/startup-selection",
            json={
                "job_id": startup_job["id"],
                "candidate_id": chosen["id"],
                "expected_blueprint_revision": None,
            },
        )
        assert selected.status_code == 200
        blueprint = selected.json()
        assert blueprint["content"]["title"] == "南平重启线 2"
        locked = client.patch(
            f"/api/projects/{project_id}/director/book-blueprint",
            json={
                "content": blueprint["content"],
                "changed_fields": [],
                "lock_updates": {
                    "rebirth_year": True,
                    "ending_direction": True,
                    "relationship_design": True,
                },
                "expected_revision": blueprint["revision"],
            },
        )
        assert locked.status_code == 200
        blueprint = locked.json()
        impact = client.post(
            f"/api/projects/{project_id}/director/regeneration-impact",
            json={"target_field": "core_desire"},
        ).json()
        assert "ending_direction" in impact["locked_conflicts"]

        expansion_request = {
            "expected_revision": blueprint["revision"],
            "author_intent": "第一卷先解决家庭现金流",
            "chapter_count": 3,
            "confirm_external_processing": True,
        }
        expansion = client.post(
            f"/api/projects/{project_id}/director/expansion-jobs",
            json=expansion_request,
        )
        assert expansion.status_code == 202
        expansion_job = expansion.json()
        _run_one(client)
        expansion_result = client.get(f"/api/jobs/{expansion_job['id']}/director-expansion-result")
        assert expansion_result.status_code == 200
        applied = client.post(
            f"/api/projects/{project_id}/director/expansion-application",
            json={
                "job_id": expansion_job["id"],
                "expected_revision": blueprint["revision"],
            },
        )
        assert applied.status_code == 200
        snapshot = applied.json()
        assert len(snapshot["volume_plans"]) == 1
        assert len(snapshot["rolling_chapter_plans"]) == 3
        blueprint = snapshot["book_blueprint"]
        assert blueprint["plan_stale"] is False
        assert blueprint["locks"]["rebirth_year"] is True
        assert blueprint["locks"]["ending_direction"] is True
        assert blueprint["locks"]["relationship_design"] is True

        pipeline_request = {
            "expected_revision": 0,
            "author_intent": "首章先用订单危机建立行动力",
            "context_token_budget": 8000,
            "confirm_external_processing": True,
        }
        pipeline = client.post(
            f"/api/chapters/{chapter_id}/director-pipeline-jobs",
            json=pipeline_request,
        )
        assert pipeline.status_code == 202
        pipeline_job = pipeline.json()
        _run_one(client)
        pipeline_result = client.get(f"/api/jobs/{pipeline_job['id']}/director-pipeline-result")
        assert pipeline_result.status_code == 200
        candidate = pipeline_result.json()
        assert candidate["completed_stages"] == ["context", "brief", "pre_review", "draft"]
        assert "厂门口的雨" in candidate["draft"]["candidate_content"]
        unchanged = client.get(f"/api/chapters/{chapter_id}").json()
        assert unchanged["content"] == ""
        assert unchanged["opening_hook"] == ""
        detail = client.get(f"/api/jobs/{pipeline_job['id']}").json()
        assert len(detail["chunks"]) == 4
        assert len(detail["attempts"]) == 2

        rerun_payload = {
            **pipeline_request,
            "parent_job_id": pipeline_job["id"],
            "rerun_from": "draft",
        }
        rerun_preview = client.post(
            f"/api/chapters/{chapter_id}/director-pipeline-preview",
            json=rerun_payload,
        )
        assert rerun_preview.status_code == 200
        assert rerun_preview.json()["estimated_calls"] == 1
        rerun = client.post(
            f"/api/chapters/{chapter_id}/director-pipeline-jobs",
            json=rerun_payload,
        )
        assert rerun.status_code == 202
        rerun_job = rerun.json()
        _run_one(client)
        rerun_detail = client.get(f"/api/jobs/{rerun_job['id']}").json()
        assert len(rerun_detail["attempts"]) == 1
        assert (
            client.get(f"/api/jobs/{rerun_job['id']}/director-pipeline-result").status_code == 200
        )

        field_request = {
            "target_field": "core_desire",
            "expected_revision": blueprint["revision"],
            "author_intent": "让欲望更具体、更能连续兑现",
            "confirm_external_processing": True,
        }
        field_job_response = client.post(
            f"/api/projects/{project_id}/director/field-jobs",
            json=field_request,
        )
        assert field_job_response.status_code == 202
        field_job = field_job_response.json()
        _run_one(client)
        updated = client.post(
            f"/api/projects/{project_id}/director/field-application",
            json={
                "job_id": field_job["id"],
                "expected_revision": blueprint["revision"],
            },
        )
        assert updated.status_code == 200
        updated_blueprint = updated.json()
        assert updated_blueprint["field_versions"]["core_desire"] == 2
        assert updated_blueprint["field_versions"]["ending_direction"] == 1
        assert updated_blueprint["content"]["rebirth_year"] == 1998
        assert (
            updated_blueprint["content"]["ending_direction"]
            == blueprint["content"]["ending_direction"]
        )
        assert (
            updated_blueprint["content"]["relationship_design"]
            == blueprint["content"]["relationship_design"]
        )
        blocked_calls = gateway.field_calls
        assert (
            client.post(
                f"/api/projects/{project_id}/director/field-preview",
                json={
                    **field_request,
                    "target_field": "ending_direction",
                    "expected_revision": updated_blueprint["revision"],
                },
            ).status_code
            == 409
        )
        assert gateway.field_calls == blocked_calls


@pytest.mark.parametrize(
    ("genre", "idea"),
    [
        ("historical_rebirth", "回到北宋边城，用账本和粮道改变一次败局"),
        ("urban_rebirth", "回到 2008 年，从一家社区店重建家庭信用"),
        ("urban_rebirth", "以真实县域竹木产业资料为锚，写一个重生创业故事"),
        ("eastern_fantasy", "边城少年以记忆为代价踏入宗门，追查测灵碑异变"),
        ("western_fantasy", "边境学徒继承禁忌誓印，在三方追捕中进入灰塔"),
    ],
)
def test_startup_cases_return_three_distinct_editable_candidates(
    tmp_path: Path,
    genre: str,
    idea: str,
) -> None:
    gateway = DirectorGateway()
    with TestClient(
        create_app(
            tmp_path / f"{genre}-{abs(hash(idea))}.db",
            AiGatewayManager(gateway),
            defer_job_runtime=True,
        )
    ) as client:
        project_id = client.post("/api/projects", json=_project_payload(genre)).json()["project"][
            "id"
        ]
        submitted = client.post(
            f"/api/projects/{project_id}/director/startup-jobs",
            json={
                "idea": idea,
                "reality_anchor": "作者提供的现实锚点",
                "candidate_count": 3,
                "confirm_external_processing": True,
            },
        ).json()
        _run_one(client)
        candidates = client.get(f"/api/jobs/{submitted['id']}/director-startup-result").json()[
            "candidates"
        ]
        assert len({item["blueprint"]["core_selling_points"][0] for item in candidates}) == 3
        assert all(item["blueprint"]["genre"] == genre for item in candidates)


def test_director_cost_limit_blocks_before_provider_call(tmp_path: Path) -> None:
    database_path = tmp_path / "priced-director.db"
    database = Database(database_path)
    database.initialize()
    profiles = ModelProfileRepository(database)
    profile = profiles.create_profile(
        CreateModelProfileRequest(
            name="计价导演线路",
            provider=ProviderKind.OPENAI,
            base_url="https://api.openai.com/v1",
            model="director-test-v1",
            input_cost_microusd_per_million=1_000_000,
            output_cost_microusd_per_million=1_000_000,
        )
    )
    profiles.set_task_default(
        AiTaskType.REVIEW,
        UpdateAiTaskDefaultRequest(profile_id=profile.id),
    )
    gateway = DirectorGateway(profile.id)
    with TestClient(
        create_app(
            database_path,
            AiGatewayManager(gateway),
            defer_job_runtime=True,
        )
    ) as client:
        project_id = client.post("/api/projects", json=_project_payload()).json()["project"]["id"]
        request = {
            "idea": "回到九八年救下一家工厂",
            "candidate_count": 3,
        }
        preview = client.post(
            f"/api/projects/{project_id}/director/startup-preview",
            json=request,
        ).json()
        assert preview["estimated_cost_microusd"] > 0
        blocked = client.post(
            f"/api/projects/{project_id}/director/startup-jobs",
            json={
                **request,
                "confirm_external_processing": True,
                "max_estimated_cost_microusd": 0,
            },
        )
        assert blocked.status_code == 409
        assert gateway.startup_calls == 0
