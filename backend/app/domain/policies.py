from enum import StrEnum


class PolicyEffect(StrEnum):
    ALLOW = "allow"
    DENY = "deny"


class AutonomyLevel(StrEnum):
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"
