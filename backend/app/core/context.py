from contextvars import ContextVar, Token

request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)
trace_id_context: ContextVar[str | None] = ContextVar("trace_id", default=None)


def bind_request_context(
    request_id: str,
    trace_id: str,
) -> tuple[Token[str | None], Token[str | None]]:
    return request_id_context.set(request_id), trace_id_context.set(trace_id)


def reset_request_context(tokens: tuple[Token[str | None], Token[str | None]]) -> None:
    request_id_context.reset(tokens[0])
    trace_id_context.reset(tokens[1])
