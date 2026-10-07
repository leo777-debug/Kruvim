"""Workspace-only observational comparison; no cross-tenant training or causal claims."""
from collections import defaultdict

import numpy as np


def comparison(rows):
    groups = defaultdict(list)
    seen = set()
    for row in rows:
        if not row.get("memory_eligible") or row.get("first_impression_score") is None:
            continue
        # One observation per run/platform, so A/B variants are not independent tests.
        key = (row["simulation_id"], row["platform"])
        if key in seen or row.get("variant", "A") != "A":
            continue
        seen.add(key)
        for metric in ("retention", "engagement_rate", "views"):
            value = row.get(metric)
            if value is not None and np.isfinite(value) and value >= 0:
                groups[(row["platform"], row.get("format"), metric)].append(row)
    findings = []
    for (platform, format_key, metric), data in groups.items():
        with_memory = [row for row in data if row.get("memory_used") and not row.get("fresh_audience")]
        fresh = [row for row in data if row.get("fresh_audience")]
        if len(with_memory) < 3 or len(fresh) < 3:
            continue
        data = with_memory + fresh
        X = np.asarray([[1, row["first_impression_score"]] for row in data], dtype=float)
        y = np.asarray([row[metric] for row in data], dtype=float)
        if metric == "views":
            y = np.log1p(y)
        errors = []
        for i in range(len(data)):
            train = np.arange(len(data)) != i
            coefficients = np.linalg.lstsq(X[train], y[train], rcond=None)[0]
            errors.append(abs(float(X[i] @ coefficients) - y[i]))
        findings.append({"platform": platform, "format": format_key, "metric": metric,
            "unit": "log(1 + views)" if metric == "views" else "percentage points",
            "memory_n": len(with_memory), "fresh_n": len(fresh),
            "memory_error": round(float(np.mean(errors[:len(with_memory)])), 4),
            "fresh_error": round(float(np.mean(errors[len(with_memory):])), 4)})
    return {"available": bool(findings), "comparisons": findings, "minimum_per_group": 3,
        "method": "Memory and explicit Fresh audience tests within the same workspace, platform and format. "
            "A score-to-outcome linear calibration is refitted leaving each run out; mean absolute error is measured on that held-out run. "
            "At least three tests in each group. Dry runs, competitor tests and incomplete automatic outcome windows are excluded. "
            "Different content and non-randomized groups can confound the comparison; this does not prove a memory effect."}
