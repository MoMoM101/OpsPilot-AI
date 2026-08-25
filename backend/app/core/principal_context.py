from contextvars import ContextVar, Token

from app.domain.security import AuthenticatedPrincipal

principal_context: ContextVar[AuthenticatedPrincipal | None] = ContextVar(
    "principal",
    default=None,
)


def bind_principal(principal: AuthenticatedPrincipal) -> Token[AuthenticatedPrincipal | None]:
    return principal_context.set(principal)


def reset_principal(token: Token[AuthenticatedPrincipal | None]) -> None:
    principal_context.reset(token)
