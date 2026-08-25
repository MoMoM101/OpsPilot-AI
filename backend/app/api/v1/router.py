from fastapi import APIRouter

from app.api.v1.routes.action_capabilities import router as action_capabilities_router
from app.api.v1.routes.action_proposals import router as action_proposals_router
from app.api.v1.routes.actions import router as actions_router
from app.api.v1.routes.alerts import router as alerts_router
from app.api.v1.routes.approvals import router as approvals_router
from app.api.v1.routes.compensations import router as compensations_router
from app.api.v1.routes.connectors import router as connectors_router
from app.api.v1.routes.dashboard import router as dashboard_router
from app.api.v1.routes.demo import router as demo_router
from app.api.v1.routes.events import router as events_router
from app.api.v1.routes.evidence import router as evidence_router
from app.api.v1.routes.hypotheses import router as hypotheses_router
from app.api.v1.routes.incidents import router as incidents_router
from app.api.v1.routes.investigations import router as investigations_router
from app.api.v1.routes.lab import router as lab_router
from app.api.v1.routes.outbox import router as outbox_router
from app.api.v1.routes.plans import router as plans_router
from app.api.v1.routes.policies import router as policies_router
from app.api.v1.routes.resource_locks import router as resource_locks_router
from app.api.v1.routes.resources import router as resources_router
from app.api.v1.routes.runner_tasks import router as runner_tasks_router
from app.api.v1.routes.runners import router as runners_router
from app.api.v1.routes.security import router as security_router
from app.api.v1.routes.system import router as system_router

router = APIRouter()
router.include_router(action_capabilities_router, tags=["action-capabilities"])
router.include_router(action_proposals_router, tags=["action-proposals"])
router.include_router(actions_router, tags=["actions"])
router.include_router(system_router, tags=["system"])
router.include_router(approvals_router, tags=["approvals"])
router.include_router(compensations_router, tags=["compensations"])
router.include_router(connectors_router, tags=["connectors"])
router.include_router(security_router, tags=["security"])
router.include_router(outbox_router, tags=["outbox"])
router.include_router(alerts_router, tags=["alerts"])
router.include_router(dashboard_router, tags=["dashboard"])
router.include_router(demo_router, tags=["demo"])
router.include_router(events_router, tags=["events"])
router.include_router(evidence_router, tags=["evidence"])
router.include_router(resources_router, tags=["resources"])
router.include_router(resource_locks_router, tags=["resource-locks"])
router.include_router(runners_router, tags=["runners"])
router.include_router(runner_tasks_router, tags=["runner-tasks"])
router.include_router(hypotheses_router, tags=["hypotheses"])
router.include_router(investigations_router, tags=["investigations"])
router.include_router(lab_router, tags=["fault-lab"])
router.include_router(incidents_router, tags=["incidents"])
router.include_router(plans_router, tags=["plans"])
router.include_router(policies_router, tags=["policies"])
