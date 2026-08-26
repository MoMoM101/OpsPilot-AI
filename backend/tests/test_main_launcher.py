from __future__ import annotations

import importlib.util
import os
import stat
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


def _load_launcher() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "main.py"
    spec = importlib.util.spec_from_file_location("opspilot_launcher", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_compose_command_adds_lab_overlay_and_profiles() -> None:
    launcher = _load_launcher()

    standard = launcher.compose_command(lab=False)
    lab = launcher.compose_command(lab=True)

    assert standard[:3] == ["docker", "compose", "-f"]
    assert standard[-1].endswith("docker-compose.yml")
    assert lab[-5:] == [
        str(launcher.ROOT / "docker-compose.lab.yml"),
        "--profile",
        "runner",
        "--profile",
        "lab",
    ]


def test_compose_secrets_are_created_once_and_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    launcher = _load_launcher()
    monkeypatch.setattr(launcher, "ROOT", tmp_path)
    monkeypatch.setattr(launcher, "SECRETS_DIRECTORY", tmp_path / ".secrets")
    monkeypatch.setenv("OPSPILOT_POSTGRES_PASSWORD", "known-database-password")

    created = launcher.ensure_compose_secrets()
    postgres = launcher.SECRETS_DIRECTORY / "postgres_password"
    assert len(created) == 4
    assert postgres.read_text(encoding="utf-8") == "known-database-password"

    monkeypatch.setenv("OPSPILOT_POSTGRES_PASSWORD", "replacement-must-not-win")
    assert launcher.ensure_compose_secrets() == []
    assert postgres.read_text(encoding="utf-8") == "known-database-password"


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission contract")
def test_compose_secrets_are_container_readable_inside_owner_only_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    launcher = _load_launcher()
    monkeypatch.setattr(launcher, "ROOT", tmp_path)
    monkeypatch.setattr(launcher, "SECRETS_DIRECTORY", tmp_path / ".secrets")

    launcher.ensure_compose_secrets()
    secret = launcher.SECRETS_DIRECTORY / "postgres_password"
    assert stat.S_IMODE(launcher.SECRETS_DIRECTORY.stat().st_mode) == 0o700
    assert stat.S_IMODE(secret.stat().st_mode) == 0o644

    secret.chmod(0o600)
    launcher.ensure_compose_secrets()
    assert stat.S_IMODE(secret.stat().st_mode) == 0o644


def test_health_probe_accepts_non_json_success(monkeypatch: pytest.MonkeyPatch) -> None:
    launcher = _load_launcher()

    class Response:
        status = 204

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *args: Any) -> None:
            return None

    monkeypatch.setattr(launcher.urllib.request, "urlopen", lambda *_args, **_kwargs: Response())

    assert launcher._http_ready("http://127.0.0.1/healthz") is True
