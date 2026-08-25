"""Cross-platform OpsPilot development and demo launcher."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import NoReturn

ROOT = Path(__file__).resolve().parent
SECRETS_DIRECTORY = ROOT / ".secrets"
SECRET_FILES = {
    "OPSPILOT_POSTGRES_PASSWORD": "postgres_password",
    "OPSPILOT_ALERTMANAGER_WEBHOOK_TOKEN": "alertmanager_webhook_token",
    "OPSPILOT_RUNNER_BOOTSTRAP_TOKEN": "runner_bootstrap_token",
    "OPSPILOT_CONTROL_PLANE_BOOTSTRAP_TOKEN": "control_plane_bootstrap_token",
}


def _fail(message: str, exit_code: int = 1) -> NoReturn:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(exit_code)


def _env_file_values() -> dict[str, str]:
    path = ROOT / ".env"
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def ensure_compose_secrets() -> list[Path]:
    """Create missing local-only Compose secrets without replacing existing values."""
    env_values = _env_file_values()
    SECRETS_DIRECTORY.mkdir(mode=0o700, parents=True, exist_ok=True)
    created: list[Path] = []
    for environment_name, filename in SECRET_FILES.items():
        target = SECRETS_DIRECTORY / filename
        if target.exists():
            if not target.read_text(encoding="utf-8").strip():
                _fail(f"Secret file is empty: {target}")
            continue
        value = os.environ.get(environment_name) or env_values.get(environment_name)
        if not value:
            value = secrets.token_urlsafe(48)
        if "\n" in value or "\r" in value:
            _fail(f"Secret contains a newline: {environment_name}")
        target.write_text(value, encoding="utf-8")
        try:
            target.chmod(0o600)
        except OSError:
            pass
        created.append(target)
    return created


def compose_command(*, lab: bool) -> list[str]:
    command = ["docker", "compose", "-f", str(ROOT / "docker-compose.yml")]
    if lab:
        command.extend(
            [
                "-f",
                str(ROOT / "docker-compose.lab.yml"),
                "--profile",
                "runner",
                "--profile",
                "lab",
            ]
        )
    return command


def _run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+", subprocess.list2cmdline(command))
    try:
        return subprocess.run(command, cwd=ROOT, check=check, text=True)
    except FileNotFoundError:
        _fail("Docker CLI was not found. Install Docker Desktop or Docker Engine with Compose v2.")
    except subprocess.CalledProcessError as exc:
        _fail(f"Command failed with exit code {exc.returncode}", exc.returncode)


def require_docker() -> None:
    if shutil.which("docker") is None:
        _fail("Docker CLI was not found. Install Docker Desktop or Docker Engine with Compose v2.")
    result = subprocess.run(
        ["docker", "compose", "version"],
        cwd=ROOT,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        _fail(
            "Docker Compose v2 is unavailable or the Docker daemon cannot be accessed. "
            "On Linux, ensure the current user can access the Docker socket."
        )


def _http_json(url: str) -> dict[str, object] | None:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _http_ready(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            status = int(response.status)
            return 200 <= status < 300
    except (OSError, urllib.error.URLError):
        return False


def _wait_for(url: str, timeout_seconds: int, label: str) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _http_ready(url):
            print(f"READY: {label}")
            return
        time.sleep(2)
    _fail(f"Timed out waiting for {label}. Run 'python main.py logs' for diagnostics.")


def start(args: argparse.Namespace) -> None:
    require_docker()
    created = ensure_compose_secrets()
    if created:
        print(f"Created {len(created)} local secret file(s) in {SECRETS_DIRECTORY}")
    command = compose_command(lab=args.lab)
    command.extend(["up", "-d"])
    if not args.no_build:
        command.append("--build")
    services = ["postgres", "backend", "frontend"]
    if args.lab:
        services.extend(
            ["runner", "qdrant", "toxiproxy", "embedding", "rag-api", "lab-controller"]
        )
    command.extend(services)
    _run(command)
    _wait_for("http://127.0.0.1:8000/api/v1/ready", args.timeout, "OpsPilot Backend")
    _wait_for("http://127.0.0.1:8080/healthz", args.timeout, "OpsPilot Frontend")
    if args.lab:
        _wait_for("http://127.0.0.1:18000/health", args.timeout, "Fault Lab RAG API")

    setup = _http_json("http://127.0.0.1:8000/api/v1/setup/status") or {}
    print("\nOpsPilot is running:")
    print("  Console:  http://127.0.0.1:8080")
    print("  Backend:  http://127.0.0.1:8000")
    if args.lab:
        print("  Fault Lab RAG API: http://127.0.0.1:18000")
    if setup.get("initialAdminCreated") is False:
        print("  First Admin setup is required.")
        print(f"  Bootstrap credential file: {SECRETS_DIRECTORY / 'control_plane_bootstrap_token'}")
    if not args.no_open:
        webbrowser.open("http://127.0.0.1:8080")


def stop(args: argparse.Namespace) -> None:
    require_docker()
    command = compose_command(lab=args.lab)
    command.append("down")
    if args.remove_volumes:
        command.append("--volumes")
    command.append("--remove-orphans")
    _run(command)


def status(args: argparse.Namespace) -> None:
    require_docker()
    _run([*compose_command(lab=args.lab), "ps"])


def logs(args: argparse.Namespace) -> None:
    require_docker()
    command = [*compose_command(lab=args.lab), "logs", "--tail", str(args.tail)]
    if args.follow:
        command.append("--follow")
    if args.services:
        command.extend(args.services)
    _run(command)


def doctor(args: argparse.Namespace) -> None:
    require_docker()
    ensure_compose_secrets()
    _run([*compose_command(lab=args.lab), "config", "--quiet"])
    print(f"Python: {sys.version.split()[0]}")
    print(f"Platform: {sys.platform}")
    print("Docker Compose configuration is valid.")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Start and inspect the local OpsPilot stack on Windows, Linux, or macOS."
    )
    subparsers = root.add_subparsers(dest="command")

    start_parser = subparsers.add_parser("start", help="Build and start OpsPilot")
    start_parser.add_argument("--lab", action="store_true", help="Include Runner and Fault Lab")
    start_parser.add_argument("--no-build", action="store_true", help="Reuse existing images")
    start_parser.add_argument("--no-open", action="store_true", help="Do not open the console")
    start_parser.add_argument("--timeout", type=int, default=300, help="Readiness timeout in seconds")
    start_parser.set_defaults(handler=start)

    stop_parser = subparsers.add_parser("stop", help="Stop OpsPilot without deleting data")
    stop_parser.add_argument("--lab", action="store_true", help="Include Fault Lab services")
    stop_parser.add_argument(
        "--remove-volumes",
        action="store_true",
        help="Also permanently delete local database and Lab volumes",
    )
    stop_parser.set_defaults(handler=stop)

    status_parser = subparsers.add_parser("status", help="Show Compose service status")
    status_parser.add_argument("--lab", action="store_true", help="Include Fault Lab services")
    status_parser.set_defaults(handler=status)

    logs_parser = subparsers.add_parser("logs", help="Show Compose logs")
    logs_parser.add_argument("services", nargs="*", help="Optional service names")
    logs_parser.add_argument("--lab", action="store_true", help="Include Fault Lab services")
    logs_parser.add_argument("--follow", action="store_true", help="Follow new log output")
    logs_parser.add_argument("--tail", type=int, default=200, help="Lines per service")
    logs_parser.set_defaults(handler=logs)

    doctor_parser = subparsers.add_parser("doctor", help="Validate Docker and Compose configuration")
    doctor_parser.add_argument("--lab", action="store_true", help="Validate the Fault Lab overlay")
    doctor_parser.set_defaults(handler=doctor)
    return root


def main() -> None:
    command_parser = parser()
    arguments = command_parser.parse_args()
    if arguments.command is None:
        arguments = command_parser.parse_args(["start"])
    arguments.handler(arguments)


if __name__ == "__main__":
    main()
