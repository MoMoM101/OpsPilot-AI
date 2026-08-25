from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    summary: str
    output: str
    redacted: bool
    truncated: bool


class ConnectorError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ReadOnlyConnector(ABC):
    name: str

    @property
    @abstractmethod
    def observe_operations(self) -> tuple[str, ...]: ...

    @abstractmethod
    async def execute(
        self,
        operation: str,
        parameters: dict[str, Any],
        timeout_seconds: int,
    ) -> ExecutionResult: ...


@dataclass(frozen=True, slots=True)
class ActionResult:
    summary: str


class ActionConnector(ABC):
    name: str

    @property
    @abstractmethod
    def action_operations(self) -> tuple[str, ...]: ...

    @abstractmethod
    async def execute_action(
        self,
        operation: str,
        parameters: dict[str, Any],
        timeout_seconds: int,
    ) -> ActionResult: ...
