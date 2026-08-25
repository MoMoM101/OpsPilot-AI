from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class PrincipalKind(StrEnum):
    USER = "user"
    SERVICE = "service"


class PrincipalRole(StrEnum):
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"
    RUNTIME = "runtime"


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    id: UUID | None
    name: str
    kind: PrincipalKind
    role: PrincipalRole
    environment_ids: frozenset[UUID]
    unrestricted_environments: bool = False

    @property
    def actor_type(self) -> str:
        return "service" if self.kind == PrincipalKind.SERVICE else "user"

    @property
    def actor_id(self) -> str:
        return str(self.id) if self.id is not None else self.name
