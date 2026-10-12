from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core import secrets

FAKE_KEY = "sk-test-FAKE-dotenv-credential-value"


def test_secret_resolution_prefers_the_process_environment_then_dotenv_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_env, backend_env = tmp_path / "repo.env", tmp_path / "backend.env"
    repo_env.write_text('FROM_REPO="repo-value"\nSHARED=repo\nEMPTY=\n', encoding="utf-8")
    backend_env.write_text("SHARED=backend\n", encoding="utf-8")
    monkeypatch.setattr(secrets, "ENV_FILES", (backend_env, repo_env))
    monkeypatch.delenv("FROM_REPO", raising=False)
    monkeypatch.delenv("SHARED", raising=False)

    assert secrets.get_secret("FROM_REPO") == "repo-value", "quotes are stripped"
    assert secrets.get_secret("SHARED") == "backend", "the backend .env has priority, as for app settings"
    assert secrets.get_secret("EMPTY") is None and not secrets.secret_is_set("EMPTY")
    assert secrets.get_secret("MISSING") is None and secrets.get_secret(None) is None
    monkeypatch.setenv("SHARED", "process")
    assert secrets.get_secret("SHARED") == "process", "the process environment wins over files"

    repo_env.write_text("FROM_REPO=changed\n", encoding="utf-8")
    assert secrets.get_secret("FROM_REPO") == "changed", "edits to .env are picked up without a restart"


def test_registered_llm_uses_a_credential_defined_only_in_dotenv(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(f'OLS_TEST_DOTENV_KEY="{FAKE_KEY}"\n', encoding="utf-8")
    monkeypatch.setattr(secrets, "ENV_FILES", (env_file,))
    monkeypatch.delenv("OLS_TEST_DOTENV_KEY", raising=False)

    created = client.post(
        "/api/settings/llm-configurations",
        params={"actor": "tester"},
        json={"name": "From dotenv", "provider": "openai", "model": "m", "api_key_env": "OLS_TEST_DOTENV_KEY"},
    )
    assert created.status_code == 201, created.text
    config = created.json()
    assert config["api_key_present"] is True and config["configured"] is True
    assert FAKE_KEY not in created.text, "the credential value is never returned"

    captured: dict[str, Any] = {}

    class FakeModels:
        def retrieve(self, model: str) -> object:
            return object()

    class FakeOpenAI:
        def __init__(self, **options: Any) -> None:
            captured.update(options)
            self.models = FakeModels()

    import openai

    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    tested = client.post(f"/api/settings/llm-configurations/{config['id']}/test")
    assert tested.status_code == 200 and tested.json()["last_test"]["ok"] is True, tested.text
    assert captured["api_key"] == FAKE_KEY, "the key from .env reaches the provider client"
    assert FAKE_KEY not in tested.text

    monkeypatch.setattr(secrets, "ENV_FILES", ())
    missing = client.post(f"/api/settings/llm-configurations/{config['id']}/test").json()
    assert missing["last_test"]["ok"] is False and "OLS_TEST_DOTENV_KEY" in missing["last_test"]["message"]
