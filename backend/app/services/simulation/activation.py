"""Per-run selective activation; registered speakers are never removed."""


def active_limit(cfg):
    agents = cfg.get("agents") or cfg.get("overrides") or {}
    count = int(agents.get("voice", 40)) + int(agents.get("stakeholders", 5))
    value = (cfg.get("overrides") or {}).get("active_per_round")
    return min(count, int(value)) if value is not None else count


def initial_sample(cfg):
    agents = cfg.get("agents") or cfg.get("overrides") or {}
    count = int(agents.get("voice", 40))
    value = (cfg.get("overrides") or {}).get("initial_reaction_sample")
    return min(count, int(value)) if value is not None else count


def estimate(cfg):
    o = cfg.get("overrides") or {}
    rounds = max(1, int(o.get("hours", 24) * 60 / o.get("minutes_per_round", 60)))
    return {"active_per_round_limit": active_limit(cfg), "initial_impression_sample": initial_sample(cfg),
            "rounds": rounds, "discussion_turn_ceiling": rounds * active_limit(cfg),
            "cost_ceiling_estimate_usd": None, "cost_status": "unknown: provider prices not configured",
            "method": "Turn limit, not an API-request or spending guarantee; graphs, tools, memory, reports and retries add calls."}
