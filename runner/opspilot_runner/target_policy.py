import ipaddress
import re

_HOSTNAME = re.compile(
    r"^(?=.{1,253}\.?$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.?$"
)
_FORBIDDEN_METADATA_HOSTS = frozenset(
    {"instance-data", "metadata.google.internal", "metadata.goog"}
)


class TargetPolicyError(ValueError):
    pass


class ProbeTargetPolicy:
    def __init__(self, allowed_hosts: list[str], allowed_ports: list[int]) -> None:
        self.allowed_hosts = tuple(self._normalize_rule(rule) for rule in allowed_hosts)
        invalid_ports = [port for port in allowed_ports if not 1 <= port <= 65535]
        if invalid_ports:
            raise ValueError("Configured probe ports must be between 1 and 65535")
        self.allowed_ports = frozenset(allowed_ports)

    def validate(self, host: str, port: int) -> str:
        normalized = self.normalize_host(host)
        if self._is_metadata_target(normalized):
            raise TargetPolicyError("Cloud metadata and link-local targets are forbidden")
        if port not in self.allowed_ports:
            raise TargetPolicyError("Probe target port is not allowlisted")
        if not any(self._matches(normalized, rule) for rule in self.allowed_hosts):
            raise TargetPolicyError("Probe target host is not allowlisted")
        return normalized

    @staticmethod
    def _is_metadata_target(host: str) -> bool:
        if host in _FORBIDDEN_METADATA_HOSTS:
            return True
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return False
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
            address = address.ipv4_mapped
        return address.is_link_local

    @staticmethod
    def normalize_host(host: str) -> str:
        value = host.strip().rstrip(".").lower()
        if not value:
            raise TargetPolicyError("Probe target host is empty")
        try:
            return str(ipaddress.ip_address(value))
        except ValueError:
            pass
        try:
            ascii_host = value.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise TargetPolicyError("Probe target host is invalid") from exc
        if not _HOSTNAME.fullmatch(ascii_host):
            raise TargetPolicyError("Probe target host is invalid")
        return ascii_host

    @classmethod
    def _normalize_rule(cls, rule: str) -> str:
        value = rule.strip().lower()
        if value.startswith("*."):
            return "*." + cls.normalize_host(value[2:])
        return cls.normalize_host(value)

    @staticmethod
    def _matches(host: str, rule: str) -> bool:
        if rule.startswith("*."):
            suffix = rule[1:]
            return host.endswith(suffix) and host != rule[2:]
        return host == rule
