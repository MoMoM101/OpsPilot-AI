from collections.abc import Sequence
from pathlib import Path

import pytest

from opspilot_runner.config import RunnerSettings
from opspilot_runner.connectors.file_logs import FileLogConnector, FileLogConnectorError
from opspilot_runner.connectors.journal import JournalConnector, JournalConnectorError
from opspilot_runner.registry import ConnectorRegistry


class FakeJournalConnector(JournalConnector):
    async def _run(self, arguments: Sequence[str], timeout_seconds: int) -> str:
        return "token=unsafe-value\nservice ready"


@pytest.mark.asyncio
async def test_file_log_connector_reads_only_allowed_root_and_redacts(tmp_path: Path) -> None:
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    log_file = allowed_root / "service.log"
    log_file.write_text("old\ntoken=unsafe-value\nservice ready\n", encoding="utf-8")
    connector = FileLogConnector([allowed_root], max_output_bytes=1024)

    result = await connector.execute(
        "file.tail",
        {"path": str(log_file), "lines": 2},
        10,
    )

    assert result.redacted is True
    assert "unsafe-value" not in result.output
    assert "service ready" in result.output
    assert "old" not in result.output


@pytest.mark.asyncio
async def test_file_log_connector_rejects_outside_path(tmp_path: Path) -> None:
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    outside = tmp_path / "outside.log"
    outside.write_text("private", encoding="utf-8")

    with pytest.raises(FileLogConnectorError) as error:
        await FileLogConnector([allowed_root]).execute(
            "file.tail",
            {"path": str(outside)},
            10,
        )

    assert error.value.code == "LOG_PATH_OUTSIDE_ALLOWED_ROOTS"


def test_journal_connector_builds_fixed_allowlisted_arguments() -> None:
    connector = JournalConnector(["docker.service"])

    arguments = connector._arguments(
        "journal.query",
        {
            "unit": "docker.service",
            "lines": 50,
            "sinceMinutes": 10,
            "priority": 4,
        },
    )

    assert arguments == [
        "--unit",
        "docker.service",
        "--since",
        "-10 minutes",
        "--lines",
        "50",
        "--no-pager",
        "--output",
        "short-iso",
        "--priority",
        "4",
    ]


def test_journal_connector_rejects_non_allowlisted_unit() -> None:
    with pytest.raises(JournalConnectorError) as error:
        JournalConnector(["docker.service"])._arguments(
            "journal.query",
            {"unit": "ssh.service"},
        )

    assert error.value.code == "JOURNAL_UNIT_NOT_ALLOWED"


@pytest.mark.asyncio
async def test_journal_connector_redacts_locally() -> None:
    connector = FakeJournalConnector(["docker.service"])

    result = await connector.execute(
        "journal.query",
        {"unit": "docker.service"},
        10,
    )

    assert result.redacted is True
    assert "unsafe-value" not in result.output


def test_registry_advertises_only_configured_log_connectors(tmp_path: Path) -> None:
    docker_only = ConnectorRegistry(RunnerSettings())
    configured = ConnectorRegistry(
        RunnerSettings(
            log_allowed_roots=[tmp_path],
            journal_allowed_units=["docker.service"],
        )
    )

    assert [item["connector"] for item in docker_only.capabilities()] == [
        "docker",
        "host",
    ]
    assert [item["connector"] for item in configured.capabilities()] == [
        "docker",
        "host",
        "file",
        "journal",
    ]
