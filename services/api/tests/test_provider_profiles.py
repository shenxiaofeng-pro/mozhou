from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def openai_profile(name: str = "OpenAI 主力") -> dict[str, object]:
    return {
        "name": name,
        "provider": "openai",
        "base_url": "https://api.openai.com/v1/",
        "model": "gpt-5.6",
        "input_cost_microusd_per_million": 2_500_000,
        "output_cost_microusd_per_million": 15_000_000,
    }


def test_profile_crud_persists_only_non_secret_metadata(tmp_path: Path) -> None:
    database_path = tmp_path / "profiles.db"
    with TestClient(create_app(database_path)) as client:
        created = client.post("/api/ai/profiles", json=openai_profile())
        profile = created.json()
        listed = client.get("/api/ai/profiles")
        updated = client.put(
            f"/api/ai/profiles/{profile['id']}",
            json={
                **openai_profile("OpenAI 长文"),
                "model": "gpt-5.6-long",
                "expected_revision": profile["revision"],
            },
        )
        deleted = client.delete(
            f"/api/ai/profiles/{profile['id']}",
            params={"expected_revision": updated.json()["revision"]},
        )

    assert created.status_code == 201
    assert profile["base_url"] == "https://api.openai.com/v1"
    assert profile["capabilities"] == {
        "structured_output": True,
        "streaming": True,
        "server_cancellation": False,
        "usage": True,
    }
    assert "api_key" not in created.text
    assert listed.json() == [profile]
    assert updated.status_code == 200
    assert updated.json()["revision"] == 1
    assert updated.json()["model"] == "gpt-5.6-long"
    assert deleted.status_code == 204

    database_bytes = database_path.read_bytes()
    assert b"api_key" not in database_bytes


def test_compatible_profile_starts_with_conservative_capabilities(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "compatible.db")) as client:
        created = client.post(
            "/api/ai/profiles",
            json={
                "name": "本地兼容端点",
                "provider": "openai_compatible",
                "base_url": "http://127.0.0.1:11434/v1/",
                "model": "writer-model:latest",
            },
        )

    assert created.status_code == 201
    assert created.json()["base_url"] == "http://127.0.0.1:11434/v1"
    assert created.json()["capabilities"] == {
        "structured_output": False,
        "streaming": False,
        "server_cancellation": False,
        "usage": False,
    }


def test_profile_rejects_unsafe_or_mismatched_provider_urls(tmp_path: Path) -> None:
    unsafe_urls = [
        "http://models.example.com/v1",
        "https://user:secret@models.example.com/v1",
        "https://models.example.com/v1?token=secret",
        "file:///tmp/provider",
    ]
    with TestClient(create_app(tmp_path / "unsafe.db")) as client:
        responses = [
            client.post(
                "/api/ai/profiles",
                json={
                    "name": f"不安全端点 {index}",
                    "provider": "openai_compatible",
                    "base_url": value,
                    "model": "writer",
                },
            )
            for index, value in enumerate(unsafe_urls)
        ]
        mismatched = client.post(
            "/api/ai/profiles",
            json={
                "name": "伪装 OpenAI",
                "provider": "openai",
                "base_url": "https://models.example.com/v1",
                "model": "gpt-5.6",
            },
        )

    assert all(response.status_code == 422 for response in responses)
    assert mismatched.status_code == 422
    assert all("secret" not in response.text for response in responses)


def test_profile_names_are_unique_and_updates_use_revision_gate(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "revision.db")) as client:
        first = client.post("/api/ai/profiles", json=openai_profile()).json()
        duplicate = client.post("/api/ai/profiles", json=openai_profile("openai 主力"))
        updated = client.put(
            f"/api/ai/profiles/{first['id']}",
            json={**openai_profile("OpenAI 备用"), "expected_revision": 0},
        )
        stale = client.put(
            f"/api/ai/profiles/{first['id']}",
            json={**openai_profile("OpenAI 过期修改"), "expected_revision": 0},
        )

    assert duplicate.status_code == 409
    assert updated.status_code == 200
    assert stale.status_code == 409


def test_profile_activation_binds_runtime_without_echoing_or_persisting_key(tmp_path: Path) -> None:
    database_path = tmp_path / "activation.db"
    secret = "compatible-runtime-secret-abcdefghijklmnopqrstuvwxyz"
    with TestClient(create_app(database_path)) as client:
        profile = client.post(
            "/api/ai/profiles",
            json={
                "name": "兼容端点",
                "provider": "openai_compatible",
                "base_url": "https://models.example.com/v1",
                "model": "writer-model",
            },
        ).json()
        activated = client.post(
            f"/api/ai/profiles/{profile['id']}/activate",
            json={"api_key": secret},
        )
        status = client.get("/api/ai/status")
        delete_active = client.delete(
            f"/api/ai/profiles/{profile['id']}",
            params={"expected_revision": profile["revision"]},
        )

    assert activated.status_code == 200
    assert activated.json() == {
        "configured": True,
        "provider": "openai_compatible",
        "model": "writer-model",
        "key_source": "runtime",
        "profile_id": profile["id"],
        "profile_name": "兼容端点",
    }
    assert status.json() == activated.json()
    assert secret not in activated.text
    assert secret.encode() not in database_path.read_bytes()
    assert delete_active.status_code == 409


def test_task_defaults_support_multiple_routes_revision_gates_and_cascade(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "task-defaults.db")) as client:
        brief_profile = client.post(
            "/api/ai/profiles",
            json=openai_profile("章纲线路"),
        ).json()
        draft_profile = client.post(
            "/api/ai/profiles",
            json=openai_profile("正文线路"),
        ).json()
        initially_empty = client.get("/api/ai/task-defaults")
        brief_default = client.put(
            "/api/ai/task-defaults/chapter_brief",
            json={"profile_id": brief_profile["id"], "expected_revision": None},
        )
        draft_default = client.put(
            "/api/ai/task-defaults/chapter_draft",
            json={"profile_id": draft_profile["id"], "expected_revision": None},
        )
        switched_brief = client.put(
            "/api/ai/task-defaults/chapter_brief",
            json={"profile_id": draft_profile["id"], "expected_revision": 0},
        )
        stale = client.put(
            "/api/ai/task-defaults/chapter_brief",
            json={"profile_id": brief_profile["id"], "expected_revision": 0},
        )
        deleted_profile = client.delete(
            f"/api/ai/profiles/{draft_profile['id']}",
            params={"expected_revision": draft_profile["revision"]},
        )
        after_cascade = client.get("/api/ai/task-defaults")

    assert initially_empty.json() == []
    assert brief_default.status_code == 200
    assert brief_default.json()["profile_name"] == "章纲线路"
    assert draft_default.status_code == 200
    assert switched_brief.json()["profile_id"] == draft_profile["id"]
    assert switched_brief.json()["revision"] == 1
    assert stale.status_code == 409
    assert deleted_profile.status_code == 204
    assert after_cascade.json() == []


def test_outbound_preview_uses_task_default_without_calling_provider(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "outbound-preview.db")) as client:
        profile = client.post(
            "/api/ai/profiles",
            json=openai_profile("低成本章纲"),
        ).json()
        client.put(
            "/api/ai/task-defaults/chapter_brief",
            json={"profile_id": profile["id"], "expected_revision": None},
        )
        project = client.post(
            "/api/projects",
            json={
                "title": "南平回潮",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "福建南平",
            },
        ).json()
        chapter = project["chapters"][0]
        preview = client.post(
            f"/api/chapters/{chapter['id']}/ai-brief-preview",
            json={"expected_revision": 0, "author_intent": "先救下父亲"},
        )

    assert preview.status_code == 200
    assert preview.json()["profile_id"] == profile["id"]
    assert preview.json()["profile_name"] == "低成本章纲"
    assert preview.json()["task_type"] == "chapter_brief"
    assert preview.json()["data_types"] == ["项目设定", "本章章纲", "作者创作意图"]
    assert preview.json()["character_count"] > 0
    assert preview.json()["estimated_input_tokens"] >= preview.json()["character_count"]
    assert preview.json()["estimated_output_tokens"] == 1_200
    assert preview.json()["estimated_cost_microusd"] > 0
    packet = preview.json()["context_packet"]
    assert packet["task_type"] == "chapter_brief"
    assert packet["used_tokens"] == preview.json()["estimated_input_tokens"]
    assert any(
        item["kind"] == "author_intent"
        and item["included"]
        and item["content"] == "先救下父亲"
        for item in packet["items"]
    )
