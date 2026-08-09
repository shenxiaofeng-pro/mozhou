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
