import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.auth_middleware import ControlPlaneAuthMiddleware
from app.core.config import Settings, get_settings
from app.core.control_plane_mode import ControlPlaneModeService
from app.core.errors import ValidationErrorResponse, install_exception_handlers
from app.core.https_middleware import HttpsEnforcementMiddleware
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware
from app.core.read_only_middleware import ReadOnlyControlPlaneMiddleware
from app.core.readiness import ReadinessService
from app.core.worker_health import WorkerHealthRegistry
from app.services.agent_node_handler import ProviderBackedAgentNodeHandler
from app.services.agent_provider import AgentProvider, PydanticAIAgentProvider
from app.services.agent_runtime import (
    AgentNodeHandler,
    AgentRuntimeWorker,
    UnavailableAgentNodeHandler,
    run_agent_runtime,
)
from app.services.control_plane_recovery import (
    ControlPlaneRecoveryService,
    retry_recovery_until_ready,
)
from app.services.lab_agent_provider import DeterministicLabAgentProvider
from app.services.model_diagnostics import ModelDiagnosticService
from app.services.observability import run_observability_monitor
from app.services.outbox import (
    OutboxPublisher,
    StructuredLogOutboxSink,
    WebhookOutboxSink,
    run_outbox_publisher,
)
from app.storage.database import Database


def create_app(
    settings: Settings | None = None,
    agent_node_handler: AgentNodeHandler | None = None,
    agent_provider: AgentProvider | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)
    logger = get_logger(__name__)
    database = Database(resolved_settings.database_url)
    configured_provider = agent_provider
    if resolved_settings.agent_runtime_enabled and configured_provider is None:
        if resolved_settings.agent_provider == "lab_deterministic":
            configured_provider = DeterministicLabAgentProvider()
        else:
            assert resolved_settings.agent_model_name is not None
            assert resolved_settings.agent_model_api_key is not None
            configured_provider = PydanticAIAgentProvider.openai_compatible(
                model_name=resolved_settings.agent_model_name,
                api_key=resolved_settings.agent_model_api_key,
                base_url=resolved_settings.agent_model_base_url,
                request_limit=resolved_settings.agent_model_request_limit,
                input_tokens_limit=resolved_settings.agent_model_input_tokens_limit,
                output_tokens_limit=resolved_settings.agent_model_output_tokens_limit,
            )
    recovery_enabled = bool(resolved_settings.startup_recovery_enabled)
    control_plane_mode = ControlPlaneModeService(recovery_enabled=recovery_enabled)
    control_plane_recovery = ControlPlaneRecoveryService(database, resolved_settings)
    readiness = ReadinessService()
    worker_health = WorkerHealthRegistry(
        stale_multiplier=resolved_settings.worker_health_stale_multiplier,
        error_threshold=resolved_settings.worker_health_error_threshold,
    )
    monitor_enabled = resolved_settings.environment != "test"
    outbox_enabled = (
        resolved_settings.environment != "test"
        and resolved_settings.outbox_publisher_mode != "disabled"
    )
    worker_health.register(
        "observability_monitor",
        enabled=monitor_enabled,
        interval_seconds=resolved_settings.observability_monitor_interval_seconds,
    )
    worker_health.register(
        "agent_runtime",
        enabled=resolved_settings.agent_runtime_enabled,
        interval_seconds=resolved_settings.agent_runtime_poll_interval_seconds,
    )
    worker_health.register(
        "outbox_publisher",
        enabled=outbox_enabled,
        interval_seconds=resolved_settings.outbox_publisher_interval_seconds,
    )
    if resolved_settings.database_readiness_enabled:
        readiness.register("database", database.is_ready)
    if recovery_enabled:
        readiness.register("control_plane_recovery", control_plane_mode.probe)
    if monitor_enabled:
        readiness.register(
            "worker:observability_monitor",
            lambda: worker_health.probe("observability_monitor"),
        )
    if resolved_settings.agent_runtime_enabled:
        readiness.register(
            "worker:agent_runtime",
            lambda: worker_health.probe("agent_runtime"),
        )
    if outbox_enabled:
        readiness.register(
            "worker:outbox_publisher",
            lambda: worker_health.probe("outbox_publisher"),
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info("application_started", environment=resolved_settings.environment)
        monitor_task: asyncio.Task[None] | None = None
        runtime_task: asyncio.Task[None] | None = None
        outbox_task: asyncio.Task[None] | None = None
        recovery_retry_task: asyncio.Task[None] | None = None
        if recovery_enabled and not await control_plane_mode.recover(control_plane_recovery.scan):
            recovery_retry_task = asyncio.create_task(
                retry_recovery_until_ready(
                    control_plane_mode,
                    control_plane_recovery,
                    resolved_settings.startup_recovery_retry_seconds,
                )
            )
        if monitor_enabled:
            monitor_task = asyncio.create_task(
                run_observability_monitor(
                    database,
                    resolved_settings.observability_monitor_interval_seconds,
                    worker_health,
                )
            )
            worker_health.start("observability_monitor", monitor_task)
        if resolved_settings.agent_runtime_enabled:
            configured_handler = agent_node_handler
            if configured_handler is None:
                assert configured_provider is not None
                configured_handler = ProviderBackedAgentNodeHandler(
                    database, configured_provider
                )
            worker = AgentRuntimeWorker(
                database,
                configured_handler or UnavailableAgentNodeHandler(),
                lease_seconds=resolved_settings.agent_runtime_lease_seconds,
                no_progress_limit=resolved_settings.agent_runtime_no_progress_limit,
                runner_lease_seconds=resolved_settings.runner_lease_seconds,
                runner_task_lease_seconds=resolved_settings.runner_task_lease_seconds,
                runner_task_max_output_bytes=resolved_settings.runner_task_max_output_bytes,
            )
            runtime_task = asyncio.create_task(
                run_agent_runtime(
                    worker,
                    resolved_settings.agent_runtime_poll_interval_seconds,
                    worker_health,
                )
            )
            worker_health.start("agent_runtime", runtime_task)
        if outbox_enabled:
            sink = (
                WebhookOutboxSink(
                    str(resolved_settings.outbox_webhook_url),
                    resolved_settings.outbox_webhook_token,
                    resolved_settings.outbox_webhook_timeout_seconds,
                )
                if resolved_settings.outbox_publisher_mode == "webhook"
                else StructuredLogOutboxSink()
            )
            publisher = OutboxPublisher(
                database,
                sink,
                batch_size=resolved_settings.outbox_publisher_batch_size,
                retention_days=resolved_settings.outbox_retention_days,
                max_attempts=resolved_settings.outbox_max_publish_attempts,
                retry_base_seconds=resolved_settings.outbox_retry_base_seconds,
                retry_max_seconds=resolved_settings.outbox_retry_max_seconds,
            )
            outbox_task = asyncio.create_task(
                run_outbox_publisher(
                    publisher,
                    resolved_settings.outbox_publisher_interval_seconds,
                    worker_health,
                )
            )
            worker_health.start("outbox_publisher", outbox_task)
        try:
            yield
        finally:
            if monitor_task is not None:
                monitor_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await monitor_task
            if runtime_task is not None:
                runtime_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await runtime_task
            if outbox_task is not None:
                outbox_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await outbox_task
            if recovery_retry_task is not None:
                recovery_retry_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await recovery_retry_task
            await database.dispose()
            logger.info("application_stopped")

    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        docs_url="/docs" if resolved_settings.docs_enabled else None,
        redoc_url="/redoc" if resolved_settings.docs_enabled else None,
        openapi_url="/openapi.json" if resolved_settings.docs_enabled else None,
        lifespan=lifespan,
        responses={
            422: {
                "model": ValidationErrorResponse,
                "description": "Request validation failed without echoing submitted values.",
            }
        },
    )
    app.state.settings = resolved_settings
    app.state.database = database
    app.state.readiness = readiness
    app.state.worker_health = worker_health
    app.state.control_plane_mode = control_plane_mode
    app.state.control_plane_recovery = control_plane_recovery
    app.state.model_diagnostics = ModelDiagnosticService(
        configured_provider,
        provider_name=resolved_settings.agent_provider,
        runtime_enabled=resolved_settings.agent_runtime_enabled,
        timeout_seconds=resolved_settings.agent_model_check_timeout_seconds,
        cooldown_seconds=resolved_settings.agent_model_check_cooldown_seconds,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin).rstrip("/") for origin in resolved_settings.cors_origins],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[
            "X-Request-ID",
            "X-Trace-ID",
            "X-Total-Count",
            "X-Limit",
            "X-Offset",
        ],
    )
    app.add_middleware(ReadOnlyControlPlaneMiddleware)
    app.add_middleware(ControlPlaneAuthMiddleware)
    app.add_middleware(HttpsEnforcementMiddleware)
    app.add_middleware(RequestContextMiddleware)
    install_exception_handlers(app)
    app.include_router(api_router)
    return app
