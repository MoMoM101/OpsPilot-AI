import argparse
import asyncio
from pathlib import Path

from app.evaluation.runner import evaluate, load_cases
from app.services.lab_agent_provider import DeterministicLabAgentProvider


async def _run(dataset: Path | None, output: Path | None) -> int:
    report = await evaluate(DeterministicLabAgentProvider(), load_cases(dataset))
    rendered = report.model_dump_json(indent=2)
    if output is not None:
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report.gate_passed else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the offline OpsPilot Agent Eval gate")
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    raise SystemExit(asyncio.run(_run(arguments.dataset, arguments.output)))


if __name__ == "__main__":
    main()
