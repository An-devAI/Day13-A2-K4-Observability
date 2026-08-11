from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from structlog.contextvars import bind_contextvars

from . import audit
from .agent import LabAgent
from .incidents import disable, enable, status
from .logging_config import configure_logging, get_logger
from .metrics import record_error, snapshot
from .middleware import CorrelationIdMiddleware
from .pii import hash_user_id, summarize_text
from .schemas import ChatRequest, ChatResponse
from .tracing import tracing_enabled

configure_logging()
log = get_logger()
app = FastAPI(title="Day 13 Observability Lab")
app.add_middleware(CorrelationIdMiddleware)
agent = LabAgent()


@app.on_event("startup")
async def startup() -> None:
    log.info(
        "app_started",
        service=os.getenv("APP_NAME", "day13-observability-lab"),
        env=os.getenv("APP_ENV", "dev"),
        payload={"tracing_enabled": tracing_enabled()},
    )
    audit.record(
        audit.APP_START,
        details={
            "tracing_enabled": tracing_enabled(),
            "max_output_tokens": agent.max_output_tokens,
            "incidents": status(),
        },
    )


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "tracing_enabled": tracing_enabled(), "incidents": status()}


@app.get("/metrics")
async def metrics() -> dict:
    return snapshot()


@app.post("/chat", response_model=ChatResponse)
async def chat(request: Request, body: ChatRequest) -> ChatResponse:
    bind_contextvars(
        correlation_id=request.state.correlation_id,
        user_id_hash=hash_user_id(body.user_id),
        session_id=body.session_id,
        feature=body.feature,
        model=agent.model,
        env=os.getenv("APP_ENV", "dev"),
    )

    log.info(
        "request_received",
        service="api",
        payload={"message_preview": summarize_text(body.message)},
    )
    try:
        result = agent.run(
            user_id=body.user_id,
            feature=body.feature,
            session_id=body.session_id,
            message=body.message,
        )
        log.info(
            "response_sent",
            service="api",
            latency_ms=result.latency_ms,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            cost_usd=result.cost_usd,
            quality_score=result.quality_score,
            payload={"answer_preview": summarize_text(result.answer)},
        )
        return ChatResponse(
            answer=result.answer,
            correlation_id=request.state.correlation_id,
            latency_ms=result.latency_ms,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            cost_usd=result.cost_usd,
            quality_score=result.quality_score,
        )
    except Exception as exc:  # pragma: no cover
        error_type = type(exc).__name__
        record_error(error_type)
        log.error(
            "request_failed",
            service="api",
            error_type=error_type,
            payload={"detail": str(exc), "message_preview": summarize_text(body.message)},
        )
        raise HTTPException(status_code=500, detail=error_type) from exc


def _actor(request: Request) -> str:
    """Ai gọi endpoint. Header x-actor để người chạy tự khai; mặc định là unknown."""
    return request.headers.get("x-actor", "unknown")


@app.post("/incidents/{name}/enable")
async def enable_incident(name: str, request: Request) -> JSONResponse:
    try:
        enable(name)
    except KeyError as exc:
        audit.record(
            audit.INCIDENT_ENABLE,
            actor=_actor(request),
            outcome="rejected",
            correlation_id=request.state.correlation_id,
            details={"name": name, "reason": "unknown incident"},
        )
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    log.warning("incident_enabled", service="control", payload={"name": name})
    audit.record(
        audit.INCIDENT_ENABLE,
        actor=_actor(request),
        correlation_id=request.state.correlation_id,
        details={"name": name, "incidents_after": status()},
    )
    return JSONResponse({"ok": True, "incidents": status()})


@app.post("/incidents/{name}/disable")
async def disable_incident(name: str, request: Request) -> JSONResponse:
    try:
        disable(name)
    except KeyError as exc:
        audit.record(
            audit.INCIDENT_DISABLE,
            actor=_actor(request),
            outcome="rejected",
            correlation_id=request.state.correlation_id,
            details={"name": name, "reason": "unknown incident"},
        )
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    log.warning("incident_disabled", service="control", payload={"name": name})
    audit.record(
        audit.INCIDENT_DISABLE,
        actor=_actor(request),
        correlation_id=request.state.correlation_id,
        details={"name": name, "incidents_after": status()},
    )
    return JSONResponse({"ok": True, "incidents": status()})
