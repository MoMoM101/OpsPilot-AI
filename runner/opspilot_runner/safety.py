import re

_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)((?:password|secret|token|api[_-]?key)\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"(?i)(postgres(?:ql)?|mysql|redis)://[^\s/@:]+:[^\s/@]+@"),
    re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----.*?-----END [A-Z ]+PRIVATE KEY-----", re.S),
)


def redact(value: str) -> tuple[str, bool]:
    result = value
    for pattern in _SECRET_PATTERNS:
        if pattern.groups:
            result = pattern.sub(r"\1[REDACTED]", result)
        else:
            result = pattern.sub("[REDACTED PRIVATE KEY]", result)
    return result, result != value


def truncate_utf8(value: str, max_bytes: int) -> tuple[str, bool]:
    encoded = value.encode()
    if len(encoded) <= max_bytes:
        return value, False
    return encoded[:max_bytes].decode(errors="ignore"), True
