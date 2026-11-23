"""Evaluation endpoints: run the harness in the background and fetch results."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Query, status
from sqlalchemy import select

from app.api.dependencies import ContainerDep, CurrentUser, RateLimited, SessionDep
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.evaluation.runner import load_sample_dataset, run_evaluation
from app.models.evaluation import EvaluationRun
from app.models.usage import UsageEvent
from app.schemas.rag import (
    EvalItem,
    EvaluationRunRequest,
    EvaluationRunResponse,
    EvaluationRunSummary,
    RAGSettingsUpdate,
)
from app.services.container import AppContainer
from app.services.settings_service import get_user_settings

logger = get_logger(__name__)
router = APIRouter(prefix="/evaluation", tags=["Evaluation"], dependencies=[RateLimited])


async def _execute(container: AppContainer, run_id: uuid.UUID, user_id: uuid.UUID, dataset: list[EvalItem],
                   configurations: list[RAGSettingsUpdate] | None, k: int, generate: bool) -> None:
    async with container.db.session_factory() as session:
        run = await session.get(EvaluationRun, run_id)
        if run is None:
            return
        run.status = "running"
        await session.commit()
        started = datetime.now(UTC)
        try:
            base = await get_user_settings(session, container.settings, user_id)
            report = await run_evaluation(container, session, user_id, base, dataset, configurations,
                                          k=k, generate_answers=generate)
            run.metrics = {
                "environment": report["environment"],
                "configurations": [{"name": c["name"], "metrics": c["metrics"], "errors": c["errors"]}
                                   for c in report["configurations"]],
            }
            run.results = [{"name": c["name"], "settings": c["settings"], "results": c["results"]}
                           for c in report["configurations"]]
            run.status = "completed"
        except Exception as exc:
            await session.rollback()
            logger.exception("Evaluation run failed", extra={"run_id": str(run_id)})
            run = await session.get(EvaluationRun, run_id)
            run.status = "failed"
            run.error_message = f"{type(exc).__name__}: {exc}"[:1000]
        run.completed_at = datetime.now(UTC)
        session.add(UsageEvent(user_id=user_id, event_type="eval",
                               latency_ms=(run.completed_at - started).total_seconds() * 1000,
                               success=run.status == "completed", event_metadata={"run_id": str(run_id)}))
        await session.commit()


@router.post("/run", response_model=EvaluationRunSummary, status_code=status.HTTP_202_ACCEPTED)
async def run(body: EvaluationRunRequest, background: BackgroundTasks, session: SessionDep,
              container: ContainerDep, user: CurrentUser) -> EvaluationRunSummary:
    """Queue an evaluation over the user's own indexed documents."""
    dataset = body.dataset or load_sample_dataset()
    record = EvaluationRun(
        user_id=user.id, name=body.name, status="pending",
        config={"k": body.k, "generate_answers": body.generate_answers, "items": len(dataset),
                "dataset": "custom" if body.dataset else "sample_qa.json",
                "configurations": [c.model_dump(exclude_none=True) for c in body.configurations or []]},
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    background.add_task(_execute, container, record.id, user.id, dataset, body.configurations, body.k,
                        body.generate_answers)
    return EvaluationRunSummary.model_validate(record)


@router.get("/results", response_model=list[EvaluationRunSummary])
async def results(session: SessionDep, user: CurrentUser,
                  limit: Annotated[int, Query(ge=1, le=100)] = 20) -> list[EvaluationRunSummary]:
    rows = await session.execute(select(EvaluationRun).where(EvaluationRun.user_id == user.id)
                                 .order_by(EvaluationRun.created_at.desc()).limit(limit))
    return [EvaluationRunSummary.model_validate(r) for r in rows.scalars()]


@router.get("/results/{run_id}", response_model=EvaluationRunResponse)
async def result(run_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> EvaluationRunResponse:
    row = (await session.execute(select(EvaluationRun).where(
        EvaluationRun.id == run_id, EvaluationRun.user_id == user.id))).scalar_one_or_none()
    if row is None:
        raise NotFoundError("Evaluation run not found")
    return EvaluationRunResponse.model_validate(row)
