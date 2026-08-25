from enum import StrEnum


class RunnerStatus(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"
    DRAINING = "draining"
    DISABLED = "disabled"
