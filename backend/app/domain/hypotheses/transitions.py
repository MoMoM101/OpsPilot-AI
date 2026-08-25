from app.domain.hypotheses.models import HypothesisStatus

_ALLOWED_TRANSITIONS: dict[HypothesisStatus, frozenset[HypothesisStatus]] = {
    HypothesisStatus.PROPOSED: frozenset(
        {
            HypothesisStatus.SUPPORTED,
            HypothesisStatus.WEAKENED,
            HypothesisStatus.REJECTED,
            HypothesisStatus.CONFIRMED,
        }
    ),
    HypothesisStatus.SUPPORTED: frozenset(
        {
            HypothesisStatus.WEAKENED,
            HypothesisStatus.REJECTED,
            HypothesisStatus.CONFIRMED,
        }
    ),
    HypothesisStatus.WEAKENED: frozenset({HypothesisStatus.SUPPORTED, HypothesisStatus.REJECTED}),
    HypothesisStatus.CONFIRMED: frozenset({HypothesisStatus.WEAKENED, HypothesisStatus.REJECTED}),
    HypothesisStatus.REJECTED: frozenset(),
}


def transition_hypothesis(
    current: HypothesisStatus,
    target: HypothesisStatus,
) -> HypothesisStatus:
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise ValueError(f"Hypothesis cannot transition from {current} to {target}")
    return target
