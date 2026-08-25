from enum import StrEnum


class HypothesisStatus(StrEnum):
    PROPOSED = "proposed"
    SUPPORTED = "supported"
    WEAKENED = "weakened"
    REJECTED = "rejected"
    CONFIRMED = "confirmed"
