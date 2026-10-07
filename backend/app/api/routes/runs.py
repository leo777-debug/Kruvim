from datetime import UTC, date, datetime, time, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, principal
from app.core.errors import AppError
from app.db.session import get_session
from app.models import Project, Simulation
from app.models.simulation import SIM_STATUSES

router = APIRouter(tags=["run history"])


@router.get("/runs")
async def all_runs(p: Principal = Depends(principal), s: AsyncSession = Depends(get_session),
                   q: str = Query("", max_length=200), format: str = "", platform: str = "", status: str = "",
                   review_status: Literal["", "none", "in_review", "approved", "changes_requested"] = "",
                   project_id: str = "", score_min: float | None = Query(None, ge=0, le=10),
                   score_max: float | None = Query(None, ge=0, le=10), date_from: date | None = None,
                   date_to: date | None = None, sort: Literal["newest", "oldest", "score_high", "score_low", "name"] = "newest",
                   offset: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100)):
    if status and status not in SIM_STATUSES:
        raise AppError("Unknown run status.")
    if score_min is not None and score_max is not None and score_min > score_max:
        raise AppError("Minimum score must be no greater than maximum score.")
    if date_from and date_to and date_from > date_to:
        raise AppError("Start date must be no later than end date.")
    score = case((Simulation.status == "completed", func.coalesce(Simulation.score, Simulation.results["score"]["mean"].as_float())), else_=None)
    content_format = func.coalesce(Simulation.content["format"].as_string(), Simulation.results["format"]["key"].as_string(),
                                  Simulation.content["type"].as_string())
    filters = [Simulation.org_id == p.org_id, Project.org_id == p.org_id]
    if q.strip():
        term = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        filters.append(or_(Simulation.name.ilike(term, escape="\\"), Project.name.ilike(term, escape="\\"),
                           Simulation.content["title"].as_string().ilike(term, escape="\\")))
    for value, column in ((format, content_format), (platform, Simulation.content["platform"].as_string()),
                          (status, Simulation.status), (review_status, Simulation.review_status), (project_id, Simulation.project_id)):
        if value:
            filters.append(column == value)
    if score_min is not None:
        filters.append(score >= score_min)
    if score_max is not None:
        filters.append(score <= score_max)
    if date_from:
        filters.append(Simulation.created_at >= datetime.combine(date_from, time.min, UTC))
    if date_to:
        filters.append(Simulation.created_at < datetime.combine(date_to + timedelta(days=1), time.min, UTC))
    total = (await s.execute(select(func.count()).select_from(Simulation).join(Project, Simulation.project_id == Project.id)
                             .where(*filters))).scalar()
    # Project only summary fields: never materialise each run's model/projection arrays.
    columns = [Simulation.id, Simulation.project_id, Project.name.label("project_name"), Simulation.name, Simulation.status,
               Simulation.step, Simulation.report_status, Simulation.created_at, Simulation.updated_at, Simulation.progress,
               Simulation.review_status, Simulation.credits_estimate, Simulation.parent_id, Simulation.error,
               score.label("score"), content_format.label("format"), Simulation.content["type"].as_string().label("content_type"),
               Simulation.content["platform"].as_string().label("platform"), Simulation.audience["regions"].label("regions"),
               Simulation.results["provider"]["dry"].as_boolean().label("dry"), Simulation.results["viral"]["score"].as_float().label("viral")]
    order = {"newest": Simulation.created_at.desc(), "oldest": Simulation.created_at.asc(), "score_high": score.desc().nulls_last(),
             "score_low": score.asc().nulls_last(), "name": Simulation.name.asc()}[sort]
    rows = (await s.execute(select(*columns).join(Project, Simulation.project_id == Project.id).where(*filters)
                            .order_by(order, Simulation.id).offset(offset).limit(limit))).mappings().all()
    return {"items": [{**dict(row), "regions": row["regions"] or [], "dry": bool(row["dry"])} for row in rows],
            "total": total, "offset": offset, "limit": limit}
