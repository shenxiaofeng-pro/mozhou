from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.database import Database
from app.main import create_app
from app.models import CreateProjectRequest
from app.repository import ProjectRepository
from app.sandbox import (
    CreateSandboxBranchRequest,
    CreateSandboxCandidateRequest,
    CreateSandboxRunRequest,
    CreateSandboxSnapshotRequest,
    NarrativeSandboxService,
    SandboxActor,
    SandboxConflictError,
    SandboxForcedAction,
    SandboxValidationError,
)


def _project(database: Database) -> tuple[str, str]:
    workspace = ProjectRepository(database).create_project(
        CreateProjectRequest(
            title="只用于隔离测试的沙盘作品",
            genre="urban_rebirth",
            rebirth_year=1998,
            rebirth_location="福建南平",
        )
    )
    return workspace.project.id, workspace.chapters[0].id


def _service(tmp_path: Path) -> tuple[Database, NarrativeSandboxService, str, str]:
    database = Database(tmp_path / "mozhou.db")
    database.initialize()
    project_id, chapter_id = _project(database)
    return database, NarrativeSandboxService(database), project_id, chapter_id


def _observe_actors(count: int) -> list[SandboxActor]:
    return [
        SandboxActor(
            id=f"actor_{index}",
            name=f"势力{index}",
            kind="faction",
            goal="观察局势并保存资源",
            location="福建南平",
            resources={"influence": 0},
            knowledge=[f"公开信息{index}"],
            capabilities=[],
            allowed_actions=["observe"],
            relationships={},
        )
        for index in range(1, count + 1)
    ]


def _snapshot_and_branch(
    service: NarrativeSandboxService,
    project_id: str,
    *,
    template_id: str = "urban-business",
    variables: dict[str, bool | int | str] | None = None,
) -> tuple[str, str]:
    snapshot = service.create_snapshot(
        project_id,
        CreateSandboxSnapshotRequest(label="基线快照", template_id=template_id),
    )
    branch = service.create_branch(
        snapshot.id,
        CreateSandboxBranchRequest(
            label="基线分支",
            variables=variables or {},
            seed=17,
        ),
    )
    return snapshot.id, branch.id


def _complete(service: NarrativeSandboxService, run_id: str) -> None:
    while service.get_run(run_id).state == "running" or service.get_run(run_id).state == "ready":
        service.advance_run(run_id)


def test_snapshot_reads_only_formal_sources_and_confirmed_reality(tmp_path: Path) -> None:
    database, service, project_id, chapter_id = _service(tmp_path)
    timestamp = datetime.now(UTC).isoformat()
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO story_facts (id, project_id, source_chapter_id, kind, content, created_at) "
            "VALUES (?, ?, ?, 'state_change', ?, ?)",
            (str(uuid4()), project_id, chapter_id, "正式事实", timestamp),
        )
        for layer in ("original", "novel"):
            connection.execute(
                "INSERT INTO timeline_events (id, project_id, layer, event_year, title, summary, created_at) "
                "VALUES (?, ?, ?, 1998, ?, ?, ?)",
                (str(uuid4()), project_id, layer, f"{layer}事件", "时间线摘要", timestamp),
            )
        for confirmed in (0, 1):
            connection.execute(
                """
                INSERT INTO source_cards (
                    id, project_id, source_kind, title, source_reference,
                    applicable_year_start, applicable_year_end, confidence,
                    excerpt, confirmed, revision, created_at, updated_at
                ) VALUES (?, ?, 'industry', ?, '合成测试资料', 1998, 1998,
                          'high', ?, ?, 0, ?, ?)
                """,
                (
                    str(uuid4()),
                    project_id,
                    f"资料{confirmed}",
                    f"现实资料{confirmed}",
                    confirmed,
                    timestamp,
                    timestamp,
                ),
            )

    snapshot = service.create_snapshot(
        project_id,
        CreateSandboxSnapshotRequest(label="现实基线", template_id="historical-factions"),
    )

    assert snapshot.actor_count == 5
    assert snapshot.source_counts == {
        "fact": 1,
        "timeline_original": 1,
        "timeline_novel": 1,
        "reality": 1,
    }
    assert {actor.location for actor in snapshot.actors} == {"福建南平"}


@pytest.mark.parametrize(
    ("forced", "message"),
    [
        (
            SandboxForcedAction(
                round_number=1,
                actor_id="protagonist",
                action_kind="publicize",
                location="福建南平",
            ),
            "不允许执行",
        ),
        (
            SandboxForcedAction(
                round_number=1,
                actor_id="protagonist",
                action_kind="investigate",
                location="福建南平",
                required_knowledge=["不应知道的秘密"],
            ),
            "不知道",
        ),
        (
            SandboxForcedAction(
                round_number=1,
                actor_id="protagonist",
                action_kind="negotiate",
                target_actor_id="local_office",
                location="上海",
            ),
            "不在行动地点",
        ),
    ],
)
def test_branch_rejects_illegal_knowledge_and_location_actions(
    tmp_path: Path,
    forced: SandboxForcedAction,
    message: str,
) -> None:
    _, service, project_id, _ = _service(tmp_path)
    snapshot = service.create_snapshot(
        project_id,
        CreateSandboxSnapshotRequest(label="历史快照", template_id="historical-factions"),
    )

    with pytest.raises(SandboxValidationError, match=message):
        service.create_branch(
            snapshot.id,
            CreateSandboxBranchRequest(
                label="非法分支",
                forced_actions=[forced],
            ),
        )


def test_branch_rejects_actions_without_enough_resources(tmp_path: Path) -> None:
    _, service, project_id, _ = _service(tmp_path)
    actors = _observe_actors(5)
    actors[0] = actors[0].model_copy(
        update={
            "resources": {"influence": 0, "logistics": 0},
            "capabilities": ["organization"],
            "allowed_actions": ["mobilize"],
        }
    )
    snapshot = service.create_snapshot(
        project_id,
        CreateSandboxSnapshotRequest(label="资源快照", actors=actors),
    )

    with pytest.raises(SandboxValidationError, match="资源.*不足"):
        service.create_branch(
            snapshot.id,
            CreateSandboxBranchRequest(
                label="资源不足",
                forced_actions=[
                    SandboxForcedAction(
                        round_number=1,
                        actor_id="actor_1",
                        action_kind="mobilize",
                        location="福建南平",
                    )
                ],
            ),
        )


@pytest.mark.parametrize(("actor_count", "round_count"), [(5, 3), (20, 10)])
def test_sandbox_supports_role_and_round_boundaries(
    tmp_path: Path,
    actor_count: int,
    round_count: int,
) -> None:
    _, service, project_id, _ = _service(tmp_path)
    snapshot = service.create_snapshot(
        project_id,
        CreateSandboxSnapshotRequest(
            label=f"{actor_count}角色",
            actors=_observe_actors(actor_count),
        ),
    )
    branch = service.create_branch(
        snapshot.id,
        CreateSandboxBranchRequest(label="压力分支", seed=99),
    )
    run = service.create_run(
        branch.id,
        CreateSandboxRunRequest(
            requested_rounds=round_count,
            action_budget=actor_count * round_count,
        ),
    )

    _complete(service, run.id)
    completed = service.get_run(run.id)

    assert completed.state == "completed"
    assert completed.completed_rounds == round_count
    assert completed.actions_used == actor_count * round_count
    assert all(len(round_item.actions) == actor_count for round_item in completed.rounds)


def test_cancel_restart_recovery_and_budget_limit(tmp_path: Path) -> None:
    database, service, project_id, _ = _service(tmp_path)
    _, branch_id = _snapshot_and_branch(service, project_id)
    cancelled = service.create_run(
        branch_id,
        CreateSandboxRunRequest(requested_rounds=3, action_budget=15),
    )
    service.cancel_run(cancelled.id)
    with pytest.raises(SandboxConflictError, match="已取消"):
        service.advance_run(cancelled.id)

    budgeted = service.create_run(
        branch_id,
        CreateSandboxRunRequest(requested_rounds=10, action_budget=5),
    )
    service.advance_run(budgeted.id)
    assert service.get_run(budgeted.id).state == "budget_exhausted"

    recoverable = service.create_run(
        branch_id,
        CreateSandboxRunRequest(requested_rounds=3, action_budget=15),
    )
    service.advance_run(recoverable.id)
    recovered_service = NarrativeSandboxService(database)
    recovered_service.advance_run(recoverable.id)
    recovered_service.advance_run(recoverable.id)
    recovered = recovered_service.get_run(recoverable.id)
    assert recovered.state == "completed"
    assert recovered.completed_rounds == 3


def test_branches_are_isolated_and_same_seed_replays_identically(tmp_path: Path) -> None:
    _, service, project_id, _ = _service(tmp_path)
    snapshot_id, first_branch_id = _snapshot_and_branch(
        service,
        project_id,
        variables={"竞争者降价": True},
    )
    second_branch = service.create_branch(
        snapshot_id,
        CreateSandboxBranchRequest(
            label="不降价分支",
            seed=17,
            variables={"竞争者降价": False},
        ),
    )
    first_run = service.create_run(
        first_branch_id,
        CreateSandboxRunRequest(requested_rounds=3, action_budget=15),
    )
    second_run = service.create_run(
        second_branch.id,
        CreateSandboxRunRequest(requested_rounds=3, action_budget=15),
    )
    _complete(service, first_run.id)
    _complete(service, second_run.id)

    assert service.get_run(first_run.id).current_state_sha256 != service.get_run(
        second_run.id
    ).current_state_sha256
    comparison = service.compare_runs(project_id, [first_run.id, second_run.id])
    assert comparison.comparable is True
    assert comparison.snapshot_sha256

    replay = service.replay_run(first_run.id)
    _complete(service, replay.id)
    original_rounds = service.get_run(first_run.id).rounds
    replay_rounds = service.get_run(replay.id).rounds
    assert [item.state_after_sha256 for item in original_rounds] == [
        item.state_after_sha256 for item in replay_rounds
    ]
    assert [item.actions for item in original_rounds] == [item.actions for item in replay_rounds]


def test_snapshot_tampering_is_detected_before_simulation(tmp_path: Path) -> None:
    database, service, project_id, _ = _service(tmp_path)
    snapshot_id, branch_id = _snapshot_and_branch(service, project_id)
    run = service.create_run(
        branch_id,
        CreateSandboxRunRequest(requested_rounds=3, action_budget=15),
    )
    with database.connect() as connection:
        connection.execute(
            "UPDATE sandbox_snapshots SET snapshot_json = ? WHERE id = ?",
            ('{"tampered":true}', snapshot_id),
        )

    with pytest.raises(SandboxConflictError, match="快照校验失败"):
        service.advance_run(run.id)


def test_report_interview_and_candidate_approval_never_change_canon(
    tmp_path: Path,
) -> None:
    database, service, project_id, chapter_id = _service(tmp_path)
    _, branch_id = _snapshot_and_branch(service, project_id)
    run = service.create_run(
        branch_id,
        CreateSandboxRunRequest(requested_rounds=3, action_budget=15),
    )
    _complete(service, run.id)
    with database.connect() as connection:
        before = {
            "content": connection.execute(
                "SELECT content FROM chapters WHERE id = ?", (chapter_id,)
            ).fetchone()[0],
            "facts": connection.execute(
                "SELECT COUNT(*) FROM story_facts WHERE project_id = ?", (project_id,)
            ).fetchone()[0],
            "timeline": connection.execute(
                "SELECT COUNT(*) FROM timeline_events WHERE project_id = ?", (project_id,)
            ).fetchone()[0],
        }

    report = service.report(run.id)
    interview = service.interview(run.id, "new_company")
    candidate = service.create_candidate(
        run.id,
        CreateSandboxCandidateRequest(
            kind="fact_change",
            source_round=1,
            target_chapter_id=chapter_id,
            title="第一轮局势候选",
        ),
    )
    approved = service.decide_candidate(candidate.id, "approve")

    assert report.conclusions
    assert all(
        item.assumptions
        and item.evidence
        and item.impact_chain
        and item.counterexample
        for item in report.conclusions
    )
    assert "不是历史事实" in report.disclaimer
    assert "快照内知识" in interview.disclaimer
    assert approved.state == "approved"
    assert approved.content["proposed_changes"]
    with pytest.raises(SandboxConflictError, match="已经处理"):
        service.decide_candidate(candidate.id, "approve")
    with database.connect() as connection:
        after = {
            "content": connection.execute(
                "SELECT content FROM chapters WHERE id = ?", (chapter_id,)
            ).fetchone()[0],
            "facts": connection.execute(
                "SELECT COUNT(*) FROM story_facts WHERE project_id = ?", (project_id,)
            ).fetchone()[0],
            "timeline": connection.execute(
                "SELECT COUNT(*) FROM timeline_events WHERE project_id = ?", (project_id,)
            ).fetchone()[0],
        }
    assert after == before


def test_sandbox_api_runs_fixed_urban_scenario_and_keeps_project_archive_clean(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(tmp_path / "mozhou.db", defer_job_runtime=True)) as client:
        workspace = client.post(
            "/api/projects",
            json={
                "title": "都市商战沙盘",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "福建南平",
            },
        ).json()
        project_id = workspace["project"]["id"]
        templates = client.get("/api/sandbox/templates")
        snapshot = client.post(
            f"/api/projects/{project_id}/sandbox/snapshots",
            json={"label": "都市基线", "template_id": "urban-business"},
        )
        branch = client.post(
            f"/api/sandbox/snapshots/{snapshot.json()['id']}/branches",
            json={
                "label": "降价分支",
                "seed": 11,
                "variables": {"竞争者降价": True},
            },
        )
        run = client.post(
            f"/api/sandbox/branches/{branch.json()['id']}/runs",
            json={"requested_rounds": 3, "action_budget": 15},
        )
        run_id = run.json()["id"]
        for _ in range(3):
            advanced = client.post(f"/api/sandbox/runs/{run_id}/advance")
        report = client.get(f"/api/sandbox/runs/{run_id}/report")
        archive = client.get(f"/api/projects/{project_id}/export")

    assert templates.status_code == 200
    assert {item["id"] for item in templates.json()} == {
        "historical-factions",
        "urban-business",
        "eastern-sect-conflict",
        "western-kingdom-crisis",
    }
    assert all(item["genres"] for item in templates.json())
    assert snapshot.status_code == 201
    assert branch.status_code == 201
    assert run.status_code == 201
    assert advanced.status_code == 200
    assert advanced.json()["state"] == "completed"
    assert report.status_code == 200
    assert len(report.json()["conclusions"]) == 15
    assert all(item["evidence"] for item in report.json()["conclusions"])
    assert all(not table.startswith("sandbox_") for table in archive.json()["tables"])
