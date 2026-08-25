from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class InvestigationGraphNode:
    key: str
    phase: str
    side_effecting: bool
    description: str


@dataclass(frozen=True, slots=True)
class InvestigationGraphDefinition:
    version: str
    entry_node: str
    nodes: tuple[InvestigationGraphNode, ...]

    @property
    def node_keys(self) -> frozenset[str]:
        return frozenset(node.key for node in self.nodes)


_GRAPH_V1 = InvestigationGraphDefinition(
    version="graph-v1",
    entry_node="load_incident",
    nodes=(
        InvestigationGraphNode(
            "load_incident", "context", False, "Load the Incident and current investigation state"
        ),
        InvestigationGraphNode(
            "load_topology", "context", False, "Load bounded resource topology context"
        ),
        InvestigationGraphNode(
            "load_recent_changes", "context", False, "Load recent changes for scoped resources"
        ),
        InvestigationGraphNode(
            "classify_complexity", "planning", False, "Choose the bounded investigation route"
        ),
        InvestigationGraphNode(
            "create_plan", "planning", True, "Create or reuse a structured investigation plan"
        ),
        InvestigationGraphNode(
            "select_next_step", "execution", False, "Select the next runnable plan step"
        ),
        InvestigationGraphNode(
            "run_investigator", "execution", True, "Dispatch bounded observational work"
        ),
        InvestigationGraphNode(
            "assess_evidence", "assessment", True, "Update hypotheses from referenced evidence"
        ),
        InvestigationGraphNode(
            "maybe_replan", "planning", True, "Decide whether a replacement plan is required"
        ),
        InvestigationGraphNode(
            "escalate_or_finish", "completion", True, "Finish or request human escalation"
        ),
    ),
)

_GRAPH_V2 = InvestigationGraphDefinition(
    version="graph-v2",
    entry_node="load_incident",
    nodes=tuple(
        [
            *(
                node
                for node in _GRAPH_V1.nodes
                if node.key not in {"maybe_replan", "escalate_or_finish"}
            ),
            InvestigationGraphNode(
                "propose_action",
                "remediation",
                True,
                "Create a policy-controlled structured Action Proposal",
            ),
            *(
                node
                for node in _GRAPH_V1.nodes
                if node.key in {"maybe_replan", "escalate_or_finish"}
            ),
        ]
    ),
)

_PUBLISHED_GRAPHS = {_GRAPH_V1.version: _GRAPH_V1, _GRAPH_V2.version: _GRAPH_V2}


def list_investigation_graphs() -> tuple[InvestigationGraphDefinition, ...]:
    return tuple(_PUBLISHED_GRAPHS.values())


def get_investigation_graph(version: str) -> InvestigationGraphDefinition | None:
    return _PUBLISHED_GRAPHS.get(version)
