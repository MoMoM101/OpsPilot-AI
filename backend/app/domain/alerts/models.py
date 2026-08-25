from enum import StrEnum


class AlertStatus(StrEnum):
    FIRING = "firing"
    RESOLVED = "resolved"
