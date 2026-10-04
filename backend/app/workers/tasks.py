"""Background jobs (arq). Each one is idempotent per simulation step and reports progress as events."""
from __future__ import annotations

import asyncio
import logging
import os
import traceback
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.core.config import settings
from app.core.errors import QuotaExceeded
from app.core.metrics import JOBS_RUNNING, SIMULATIONS
from app.db.session import session_scope
from app.models import Asset, PopulationVersion, Report, Simulation, Survey
from app.services import datapool, jobs, knowledge, lifecycle, metering, monitoring, storage
from app.services.content import ContentError, build_card, document_text, prepare
from app.services.events import bus
from app.services.interaction import survey as run_survey_fn
from app.services.llm import LLMAuthError, LLMError, Usage, make_llm
from app.services.providers import resolve
from app.services.report import generate as generate_report_fn
from app.services.simulation import Engine, agent_detail
from app.services.simulation import prepare as prepare_env

log = logging.getLogger("kruvim.jobs")
USER_ERRORS = (ContentError, LLMAuthError, LLMError, ValueError)


def _now():
    return datetime.now(UTC)


async def _set(sim_id: str, **values):
    async with session_scope() as s:
        await s.execute(update(Simulation).where(Simulation.id == sim_id).values(**values))


async def _llm_for(org_id: str):
    async with session_scope() as s:
        res = await resolve(s, org_id)
    return res, make_llm(res.settings)


async def _fail(sim_id: str, stage: str, exc: Exception, status: str = "failed"):
    msg = str(exc) if isinstance(exc, USER_ERRORS) else f"Internal error in {stage}: {exc.__class__.__name__}: {exc}"
    if not isinstance(exc, USER_ERRORS):
        log.error("job failed\n%s", traceback.format_exc(), extra={"simulation_id": sim_id, "job": stage})
    await _set(sim_id, status=status, error=msg[:2000])
    await bus.publish(sim_id, f"{stage}.failed", {"message": msg[:2000]})
    await monitoring.on_failed(sim_id, msg)


async def _autopilot(sim_id: str, step: str, attempt: int = 0) -> None:
    """Batch tests, recurring re-runs and competitor monitoring run every step without anyone clicking."""
    async with session_scope() as s:
        sim = await s.get(Simulation, sim_id)
        if not sim or not (sim.config or {}).get("autopilot"):
            return
        if step == "run" and sim.status != "ready":
            return
        try:
            if step == "environment":
                await lifecycle.queue_environment(s, sim)
            else:
                await lifecycle.queue_run(s, sim)
        except QuotaExceeded as exc:
            if exc.code == "concurrency_limit" and attempt < 720:
                sim.progress = {**(sim.progress or {}), "waiting_for_slot": True}
                await s.commit()
                await jobs.enqueue("resume_autopilot", sim_id=sim_id, attempt=attempt + 1, delay=5)
            else:
                await _fail(sim_id, "simulation", exc, status="failed")
        except Exception as exc:
            await _fail(sim_id, "simulation", exc, status="failed")


async def resume_autopilot(ctx, sim_id: str, attempt: int = 0):
    await _autopilot(sim_id, "run", attempt)


async def _asset_files(sim: Simulation, kinds: tuple[str, ...]) -> tuple[dict, list]:
    files, seeds = {}, []
    async with session_scope() as s:
        assets = (await s.execute(select(Asset).where(Asset.project_id == sim.project_id, Asset.kind.in_(kinds)))).scalars().all()
    c, vb = sim.content or {}, (sim.content or {}).get("variant_b") or {}
    wanted = {c.get("asset_id"), vb.get("asset_id"), *(c.get("asset_ids") or []), *(vb.get("asset_ids") or [])}
    seed_ids = set((sim.content or {}).get("seed_asset_ids") or [])
    for a in assets:
        if a.id in wanted:
            files[a.id] = await storage.local_file(a.storage_key, os.path.splitext(a.filename)[1])
        elif a.kind == "seed" and (not seed_ids or a.id in seed_ids):
            seeds.append((a.filename, a.text_excerpt or document_text(await storage.get(a.storage_key), a.filename)))
    return files, seeds


# ---- Step 1 --------------------------------------------------------------------------------------------
async def build_graph(ctx, sim_id: str):
    JOBS_RUNNING.labels("graph").inc()
    usage = Usage()
    res = llm = None
    try:
        async with session_scope() as s:
            sim = await s.get(Simulation, sim_id)
            org_id = sim.org_id
        res, llm = await _llm_for(org_id)
        await _set(sim_id, status="building_graph", error=None)

        async def progress(msg, frac):
            await bus.publish(sim_id, "graph.progress", {"message": msg, "progress": round(frac, 3)})

        await progress("Reading content", 0.02)
        files, seeds = await _asset_files(sim, ("content", "content_b", "seed"))
        work = os.path.join(settings.data_dir, "work", sim_id)
        meta = {"title": sim.content.get("title"), "platform": sim.content.get("platform"), "goal": sim.content.get("goal"),
                "format": sim.content.get("format")}
        prep_a = prepare(sim.content, files, os.path.join(work, "A"))
        card_a = await build_card(prep_a, meta, llm, usage)
        cards = {"A": card_a}
        vb = (sim.content or {}).get("variant_b")
        if vb:
            prep_b = prepare({**vb, "type": vb.get("type") or sim.content.get("type")}, files, os.path.join(work, "B"))
            b_title = vb.get("title") or (meta["title"] or "") + (" (competitor)" if sim.content.get("b_kind") == "competitor" else " (B)")
            cards["B"] = await build_card(prep_b, {**meta, "title": b_title}, llm, usage)
        await progress("Fetching live context from the data pool", 0.1)
        regions = (sim.audience or {}).get("regions") or datapool.context.all_codes()
        snaps = await datapool.snapshots_at(regions, sim.publish_at, llm, usage, org_id=org_id)
        if not sim.publish_at or sim.publish_at >= _now() - timedelta(hours=2):
            from app.services.datapool.targeted import prepare as prepare_targeted
            await prepare_targeted(sim_id, org_id, cards["A"], regions, snaps)
        for c in cards.values():
            c["trend"] = datapool.trend_alignment(c, snaps)
        content = dict(sim.content)
        if "B" in cards:
            content["card_b"] = cards["B"]
        cfg = dict(sim.config or {})
        cfg["context"] = snaps
        await _set(sim_id, card=cards["A"], content=content, config=cfg)
        await bus.publish(sim_id, "graph.context", {"regions": {k: {kk: v.get(kk) for kk in ("name", "city", "local_time", "weather", "brief", "brief_by")}
                                                                 for k, v in snaps.items()}})
        ontology = await knowledge.build(sim_id, sim.requirement, cards, seeds, snaps, llm, usage, progress)
        await _set(sim_id, ontology=ontology, status="graph_ready", step=2, usage={"graph": usage.as_dict(res.settings)})
        await metering.record(org_id, sim_id, "graph", usage, res)
        await bus.publish(sim_id, "graph.completed", {"ontology": ontology, "usage": usage.as_dict(res.settings)})
        await _autopilot(sim_id, "environment")
    except Exception as exc:
        await _fail(sim_id, "graph", exc)
    finally:
        JOBS_RUNNING.labels("graph").dec()
        if llm:
            await llm.aclose()


# ---- Step 2 --------------------------------------------------------------------------------------------
async def prepare_environment(ctx, sim_id: str):
    JOBS_RUNNING.labels("environment").inc()
    usage = Usage()
    llm = None
    try:
        async with session_scope() as s:
            sim = await s.get(Simulation, sim_id)
            org_id = sim.org_id
        res, llm = await _llm_for(org_id)
        await _set(sim_id, status="preparing", error=None)

        async def progress(msg, frac):
            await bus.publish(sim_id, "env.progress", {"message": msg, "progress": round(frac, 3)})

        cfg = await prepare_env(sim_id, llm, usage, progress)
        async with session_scope() as s:
            sim = await s.get(Simulation, sim_id)
            sim.status, sim.step = "ready", 2
            sim.usage = {**(sim.usage or {}), "environment": usage.as_dict(res.settings)}
        await metering.record(org_id, sim_id, "environment", usage, res)
        await bus.publish(sim_id, "env.completed", {"config": {k: v for k, v in cfg.items() if k != "context"}})
        await _autopilot(sim_id, "run")
    except Exception as exc:
        await _fail(sim_id, "env", exc, status="graph_ready")
    finally:
        JOBS_RUNNING.labels("environment").dec()
        if llm:
            await llm.aclose()


# ---- Step 3 --------------------------------------------------------------------------------------------
async def run_simulation(ctx, sim_id: str):
    JOBS_RUNNING.labels("simulation").inc()
    usage = Usage()
    llm = None
    try:
        async with session_scope() as s:
            sim = await s.get(Simulation, sim_id)
            org_id = sim.org_id
            sim.status, sim.step, sim.started_at, sim.error = "running", 3, _now(), None
        res, llm = await _llm_for(org_id)
        await bus.publish(sim_id, "simulation.started", {"rounds": sim.config["time"]["rounds"], "provider": res.settings.provider,
                                                         "dry": llm.is_dry, "voice_model": llm.model_for("voice")})
        engine = Engine(sim_id, llm, usage)
        results = await engine.run()
        results["usage"] = usage.as_dict(res.settings)
        results["provider"] = {"name": res.settings.provider, "preset": res.settings.preset, "dry": llm.is_dry, "source": res.source,
                               "voice_model": llm.model_for("voice"), "report_model": llm.model_for("report")}
        async with session_scope() as s:
            sim = await s.get(Simulation, sim_id)
            sim.results, sim.status, sim.step, sim.finished_at = results, "completed", 4, _now()
            sim.score = float(results["score"]["mean"])
            topics = (sim.card or {}).get("topics") or {}
            sim.niche = max(topics, key=topics.get) if topics else None
            sim.usage = {**(sim.usage or {}), "simulation": usage.as_dict(res.settings)}
            sim.report_status = "queued"
        from app.services.agent_memory import write_run
        await write_run(org_id, sim_id, llm, usage)
        results["usage"] = usage.as_dict(res.settings)
        credits = await metering.record(org_id, sim_id, "simulation", usage, res)
        async with session_scope() as s:
            sim = await s.get(Simulation, sim_id)
            sim.results = results
            sim.usage = {**(sim.usage or {}), "simulation": usage.as_dict(res.settings)}
            sim.credits_charged = (sim.credits_charged or 0) + credits
        from app.services.creator_memory import update_memory
        await update_memory(org_id, sim_id)
        SIMULATIONS.labels("completed").inc()
        await bus.publish(sim_id, "simulation.completed", {"score": results["score"], "viral": results["viral"]["score"],
                                                           "stopped_early": results.get("stopped_early")})
        from app.services.jobs import enqueue
        await enqueue("generate_report", sim_id=sim_id)
        await monitoring.on_completed(sim_id)
    except Exception as exc:
        SIMULATIONS.labels("failed").inc()
        await _fail(sim_id, "simulation", exc)
    finally:
        JOBS_RUNNING.labels("simulation").dec()
        if llm:
            await llm.aclose()


# ---- Step 4 --------------------------------------------------------------------------------------------
async def generate_report(ctx, sim_id: str):
    JOBS_RUNNING.labels("report").inc()
    usage = Usage()
    llm = None
    try:
        async with session_scope() as s:
            sim = await s.get(Simulation, sim_id)
            org_id = sim.org_id
            sim.report_status = "running"
        res, llm = await _llm_for(org_id)
        await generate_report_fn(sim_id, llm, usage)
        await metering.record(org_id, sim_id, "report", usage, res)
        async with session_scope() as s:
            sim = await s.get(Simulation, sim_id)
            sim.report_status, sim.step = "done", 5
            sim.usage = {**(sim.usage or {}), "report": usage.as_dict(res.settings)}
        await bus.publish(sim_id, "report.completed", {"status": "done"})
    except Exception as exc:
        msg = str(exc) if isinstance(exc, USER_ERRORS) else f"{exc.__class__.__name__}: {exc}"
        log.error("report failed\n%s", traceback.format_exc(), extra={"simulation_id": sim_id})
        async with session_scope() as s:
            await s.execute(update(Simulation).where(Simulation.id == sim_id).values(report_status="failed"))
            rep = (await s.execute(select(Report).where(Report.simulation_id == sim_id, Report.status == "running"))).scalars().first()
            if rep:
                rep.status, rep.error = "failed", msg[:2000]
        await bus.publish(sim_id, "report.failed", {"message": msg[:2000]})
    finally:
        JOBS_RUNNING.labels("report").dec()
        if llm:
            await llm.aclose()


# ---- Step 5 surveys ------------------------------------------------------------------------------------
async def run_survey(ctx, survey_id: str):
    usage = Usage()
    llm = None
    res = None
    async with session_scope() as s:
        claimed = await s.execute(update(Survey).where(Survey.id == survey_id, Survey.status == "queued").values(status="running"))
        if not claimed.rowcount:
            return
        sv = await s.get(Survey, survey_id)
        sim = await s.get(Simulation, sv.simulation_id)
    try:
        res, llm = await _llm_for(sim.org_id)
        from app.models import SimAgent
        async with session_scope() as s:
            rows = (await s.execute(select(SimAgent).where(SimAgent.simulation_id == sim.id))).scalars().all()
        f = sv.filters or {}
        if "metered" in f and (res.metered != f["metered"] or res.config_id != f.get("provider_config_id")):
            raise ValueError("The model provider changed. Preview and start the survey again.")
        if sim.status != "completed":
            raise ValueError("The simulation changed. Wait for it to complete before surveying.")
        pick = [r for r in rows if (not f.get("region") or r.region == f["region"]) and (not f.get("stance") or (r.persona or {}).get("stance") == f["stance"])
                and (not f.get("kind") or r.kind == f["kind"])][: int(f.get("n") or 12)]
        if f.get("agent_refs") is not None:
            by_ref = {r.ref: r for r in rows}
            pick = [by_ref[ref] for ref in f["agent_refs"] if ref in by_ref]
            if len(pick) != len(f["agent_refs"]):
                raise ValueError("The agents changed. Preview and start the survey again.")
        details = [await agent_detail(sim, r.ref) for r in pick]
        partial = []
        answer_lock = asyncio.Lock()

        async def on_answer(item):
            async with answer_lock:
                partial.append(item)
                async with session_scope() as s:
                    row = await s.get(Survey, survey_id)
                    row.answers = list(partial)
                await bus.publish(sim.id, "survey.answer", {"survey_id": survey_id, "answered": len(partial), "total": len(details), **item})

        out = await run_survey_fn(details, sim.card, (sim.content or {}).get("platform"), sv.question, llm, usage, on_answer)
        async with session_scope() as s:
            row = await s.get(Survey, survey_id)
            row.answers, row.summary, row.status = out["answers"], __import__("json").dumps(out["summary"], ensure_ascii=False), "done"
        await bus.publish(sim.id, "survey.completed", {"survey_id": survey_id, "summary": out["summary"]})
    except (Exception, asyncio.CancelledError) as exc:
        async with session_scope() as s:
            row = await s.get(Survey, survey_id)
            row.status, row.summary = "failed", str(exc)[:1000]
        await bus.publish(sim.id, "survey.failed", {"survey_id": survey_id, "message": str(exc)[:500]})
    finally:
        if res:
            await metering.record(sim.org_id, sim.id, "survey", usage, res)
        from app.services.quotas import ledger
        async with session_scope() as s:
            row = await s.get(Survey, survey_id)
            reserved = int((row.filters or {}).get("reserved_credits") or 0)
            if reserved:
                await ledger(s, sim.org_id, reserved, "survey_refund", survey_id)
                row.filters = {**row.filters, "reserved_credits": 0}
        if llm:
            await llm.aclose()


# ---- platform jobs ---------------------------------------------------------------------------------------
async def refresh_datapool(ctx):
    return await datapool.run_due()


async def monitoring_tick(ctx):
    return await monitoring.tick()


async def run_connector(ctx, key: str):
    return await datapool.run_connector(key)


async def build_population(ctx, version_id: str):
    import asyncio

    from app.services.population import store
    from app.services.population.generator import stats
    async with session_scope() as s:
        v = await s.get(PopulationVersion, version_id)
        v.status = "building"
        size, seed, priors = v.size, v.seed, v.priors
    try:
        pop = await asyncio.to_thread(store.build_to_disk, version_id, size, seed, priors)
        st = await asyncio.to_thread(stats, pop)
        async with session_scope() as s:
            await s.execute(update(PopulationVersion).values(is_active=False))
            v = await s.get(PopulationVersion, version_id)
            v.status, v.is_active, v.stats = "ready", True, st
    except Exception as exc:
        async with session_scope() as s:
            v = await s.get(PopulationVersion, version_id)
            v.status, v.error = "error", str(exc)[:1000]
