# Contributing to OpsPilot AI

Thank you for helping improve OpsPilot AI. The project values small, reviewable changes, explicit
safety boundaries, reproducible tests, and documentation that matches runtime behavior.

## Before opening a change

1. Search existing issues and pull requests.
2. For a substantial feature or architecture change, open a proposal before implementation.
3. Do not include real credentials, private infrastructure identifiers, customer data, production
   logs, or vulnerability details in public issues and fixtures.
4. Report security issues through the process in `SECURITY.md`.

## Development setup

OpsPilot AI supports Python 3.12/3.13 and Node.js 22.

```bash
python -m venv .venv

# Activate on Linux/macOS
source .venv/bin/activate

# Activate on Windows PowerShell
.venv\Scripts\Activate.ps1

python -m pip install -e './backend[dev]'
python -m pip install -e './runner[dev]'
python -m pip install -e './lab[dev]'
```

Install frontend dependencies:

```bash
cd frontend
npm ci
```

For the containerized stack, copy `.env.compose.example` only when you need explicit local values.
Never commit `.env` or `.secrets/`.

## Required checks

Backend:

```bash
cd backend
python -m pytest
python -m ruff check .
python -m mypy app
python -m app.evaluation
python -m alembic check
```

Runner and Fault Lab:

```bash
cd runner
python -m pytest
python -m ruff check .
python -m mypy opspilot_runner

cd ../lab
python -m pytest
python -m ruff check .
python -m mypy opspilot_lab
```

Frontend:

```bash
cd frontend
npm run openapi:check
npm test
npm run build
```

Compose:

```bash
python main.py doctor
python main.py doctor --lab
```

## Pull requests

- Keep unrelated formatting or refactoring out of a behavioral change.
- Add or update tests for all bug fixes and contract changes.
- Update OpenAPI-generated frontend types when the API contract changes.
- Include migrations for persistent schema changes and keep a single Alembic head.
- Describe security, compatibility, migration, rollback, and frontend coordination impact.
- Ensure generated caches, local databases, secret files, and build outputs are not committed.

By contributing, you agree that your contribution is licensed under Apache-2.0.

