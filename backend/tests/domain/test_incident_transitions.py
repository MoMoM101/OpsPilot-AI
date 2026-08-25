import pytest

from app.domain.incidents import IncidentStatus, IncidentTransitionError, transition_incident


def test_valid_incident_transition() -> None:
    result = transition_incident(IncidentStatus.DETECTED, IncidentStatus.CORRELATING)
    assert result is IncidentStatus.CORRELATING


def test_invalid_incident_transition_is_rejected() -> None:
    with pytest.raises(IncidentTransitionError):
        transition_incident(IncidentStatus.DETECTED, IncidentStatus.RESOLVED)
