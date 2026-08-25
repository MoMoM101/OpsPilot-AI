import json

import pytest

from opspilot_lab.controller import SCENARIOS as CONTROLLER_SCENARIOS
from opspilot_lab.scenarios import SCENARIOS

EXPECTED_SCENARIOS = {
    "qdrant_down",
    "sqlite_locked",
    "embedding_timeout",
    "backend_500",
    "collection_count_mismatch",
}
READ_OPERATIONS = {
    "sqlite.health",
    "sqlite.lock_status",
    "sqlite.integrity_check",
    "qdrant.health",
    "qdrant.collection",
    "qdrant.point_count",
    "qdrant.query_smoke",
    "rag.business_health",
}
ACTION_CAPABILITIES = {
    "container.restart",
    "service.reload",
    "traffic_probe.pause",
    "traffic_probe.resume",
    "health.check",
}


def test_all_five_versioned_manifests_are_registered_by_the_controller() -> None:
    assert set(SCENARIOS) == EXPECTED_SCENARIOS
    assert CONTROLLER_SCENARIOS is SCENARIOS


@pytest.mark.parametrize("scenario_id", sorted(EXPECTED_SCENARIOS))
def test_scenario_manifest_contains_complete_safe_acceptance_contract(
    scenario_id: str,
) -> None:
    manifest = SCENARIOS[scenario_id]

    assert manifest.version == 1
    assert set(manifest.expected_investigation) <= READ_OPERATIONS
    assert set(manifest.allowed_actions) <= ACTION_CAPABILITIES
    assert set(manifest.forbidden_actions) <= ACTION_CAPABILITIES
    assert not set(manifest.allowed_actions) & set(manifest.forbidden_actions)
    assert manifest.recovered_rag.status_code == 200
    assert manifest.recovered_rag.retrieved_point_count == 1

    serialized = json.dumps(manifest.model_dump(mode="json"), sort_keys=True).lower()
    assert "token" not in serialized
    assert "password" not in serialized
    assert "authorization" not in serialized
