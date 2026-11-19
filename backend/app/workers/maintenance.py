"""Shared UTC maintenance schedule for the external scheduler and HTTP cron trigger."""
from datetime import UTC, datetime


async def sync_analytics(ctx):
    from app.services.social_sync import sync_due
    await sync_due()


async def maintain_archive(ctx):
    from app.services.datapool.archive import compress_old
    from app.services.datapool.cultural import synthesize_daily
    await synthesize_daily()
    await compress_old()


async def consolidate_agent_memory(ctx):
    from app.services.agent_memory import consolidate
    return await consolidate()


async def watch_runs(ctx):
    from app.services.outbox import recover_interrupted
    from app.services.watchdog import check
    await recover_interrupted()
    # Separate queue jobs keep failures in one service from blocking the others.
    return await check()


async def archive_snapshots(ctx):
    from app.services.datapool.context import refresh_snapshot_archive
    return await refresh_snapshot_archive()


async def dispatch_mail(ctx):
    from app.services.mail import dispatch_pending
    return await dispatch_pending()


async def maintain_token_budget(ctx):
    from app.services.token_budget import tick
    return await tick()


# (job name, period in minutes, offset from midnight UTC).
# Select the latest slot, including on startup after a missed tick.
SCHEDULE = (
    ("refresh_datapool", 10, 0),  # includes library inbox and all due connectors
    ("monitoring_tick", 10, 5),
    ("sync_analytics", 10, 3),
    ("maintain_archive", 60, 15),
    ("consolidate_agent_memory", 1440, 150),
    ("watch_runs", 1, 0),
    ("archive_snapshots", 10, 1),
    ("dispatch_mail", 1, 0),
    ("maintain_token_budget", 1, 0),
)


async def schedule_due(pool, now=None):
    now = now or datetime.now(UTC)
    minute = int(now.timestamp()) // 60
    dispatched = 0
    for name, period, offset in SCHEDULE:
        slot = (minute - offset) // period
        job = await pool.enqueue_job(name, _job_id=f"maintenance:{name}:{slot}",
                                     _queue_name="kruvim:maintenance")
        dispatched += job is not None
    return dispatched


async def maintenance_tick(ctx):
    return await schedule_due(ctx["redis"])
