import json
from typing import Any
from uuid import UUID

from app.services.agent_provider import (
    ActionProposalOutput,
    HypothesisProposal,
    InvestigatorOutput,
    ModelConnectionProbeOutput,
    ObservationProposal,
    ObservationProposalOutput,
    PlannerOutput,
    PlanStepProposal,
    ProviderResult,
    ReplannerOutput,
)


class DeterministicLabAgentProvider:
    """Local-only deterministic decisions for reproducible Fault Lab validation."""

    async def check_connection(self) -> ProviderResult[ModelConnectionProbeOutput]:
        return self._result(ModelConnectionProbeOutput(status="ok"))

    async def plan(
        self, prompt: str, *, request_limit: int | None = None
    ) -> ProviderResult[PlannerOutput]:
        payload = self._payload(prompt)
        resource_id = UUID(str(self._incident(payload)["resourceId"]))
        operation = self._operation(self._title(payload))
        return self._result(
            PlannerOutput(
                objective="Collect one deterministic Fault Lab observation",
                steps=[
                    PlanStepProposal(
                        title=f"Observe {operation}",
                        objective="Collect bounded evidence for the injected Lab failure",
                        kind="observe",
                        resource_scope=[resource_id],
                        allowed_capabilities=[operation],
                        expected_evidence=["Runner observation bound to the Incident"],
                    )
                ],
                max_tool_calls=3,
                max_duration_seconds=300,
                summary=f"Selected the deterministic {operation} Lab observation",
            )
        )

    async def observe(
        self, prompt: str, *, request_limit: int | None = None
    ) -> ProviderResult[ObservationProposalOutput]:
        payload = self._payload(prompt)
        active = payload.get("activePlanStep")
        if not isinstance(active, dict):
            raise ValueError("Fault Lab prompt has no active PlanStep")
        operations = active.get("allowedOperations")
        resources = active.get("resourceIds")
        if not isinstance(operations, list) or not operations:
            raise ValueError("Fault Lab PlanStep has no allowed Operation")
        if not isinstance(resources, list) or not resources:
            raise ValueError("Fault Lab PlanStep has no Resource")
        return self._result(
            ObservationProposalOutput(
                action="observe",
                proposal=ObservationProposal(
                    resource_id=UUID(str(resources[0])),
                    operation=str(operations[0]),
                    purpose="Collect deterministic evidence for the active Fault Lab scenario",
                ),
                reason="The versioned Lab scenario requires this read-only observation",
            )
        )

    async def investigate(
        self, prompt: str, *, request_limit: int | None = None
    ) -> ProviderResult[InvestigatorOutput]:
        payload = self._payload(prompt)
        evidence = payload.get("evidence", [])
        evidence_ids = [
            UUID(str(item["id"]))
            for item in evidence
            if isinstance(item, dict) and item.get("id")
        ]
        hypotheses = (
            [
                HypothesisProposal(
                    summary="The injected Fault Lab dependency explains the business degradation",
                    confidence=95,
                    supporting_evidence_ids=evidence_ids,
                )
            ]
            if evidence_ids
            else []
        )
        return self._result(
            InvestigatorOutput(
                hypotheses=hypotheses,
                evidence_ids=evidence_ids,
                progressed=bool(evidence_ids),
                summary="Assessed only the Runner Evidence supplied by the control plane",
            )
        )

    async def replan(
        self, prompt: str, *, request_limit: int | None = None
    ) -> ProviderResult[ReplannerOutput]:
        payload = self._payload(prompt)
        has_evidence = bool(payload.get("evidence"))
        return self._result(
            ReplannerOutput(
                action="finish" if has_evidence else "pause",
                progressed=has_evidence,
                reason=(
                    "The deterministic Lab Evidence is sufficient"
                    if has_evidence
                    else "No Runner Evidence is available"
                ),
            )
        )

    async def propose_action(
        self, prompt: str, *, request_limit: int | None = None
    ) -> ProviderResult[ActionProposalOutput]:
        self._payload(prompt)
        return self._result(
            ActionProposalOutput(
                action="none",
                reason="Fault Lab scenarios are observation-only and require explicit cleanup",
            )
        )

    @staticmethod
    def _operation(title: str) -> str:
        lowered = title.lower()
        if "cardinality" in lowered or "count" in lowered:
            return "qdrant.point_count"
        if "vector-store" in lowered or "qdrant" in lowered:
            return "qdrant.health"
        if "sqlite" in lowered or "document storage" in lowered:
            return "sqlite.lock_status"
        return "rag.business_health"

    @staticmethod
    def _payload(prompt: str) -> dict[str, Any]:
        payload: Any = json.loads(prompt)
        if not isinstance(payload, dict):
            raise ValueError("Fault Lab prompt must contain an object")
        return payload

    @staticmethod
    def _incident(payload: dict[str, Any]) -> dict[str, Any]:
        incident = payload.get("incident")
        if not isinstance(incident, dict):
            raise ValueError("Fault Lab prompt has no Incident")
        return incident

    @classmethod
    def _title(cls, payload: dict[str, Any]) -> str:
        untrusted = cls._incident(payload).get("untrustedData")
        return str(untrusted.get("title", "")) if isinstance(untrusted, dict) else ""

    @staticmethod
    def _result[OutputT](output: OutputT) -> ProviderResult[OutputT]:
        return ProviderResult(
            output=output,
            requests=1,
            input_tokens=32,
            output_tokens=16,
        )
