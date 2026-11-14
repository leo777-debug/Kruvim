"""Provider-independent dataset preparation; no model calls or cross-run caches."""
import hashlib
import json
import re
from collections import defaultdict
from decimal import Decimal, localcontext

_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)")


def numeric_fields(text):
    """Only explicit JSON fields or labelled numeric cells; never infer from prose."""
    try:
        fields = json.loads(text, parse_float=Decimal)
    except (ValueError, TypeError):
        fields = dict(part.split(":", 1) for part in text.split(";") if ":" in part)
    if not isinstance(fields, dict):
        return {}
    result = {}
    for label, raw in fields.items():
        label = str(label).strip()[:80]
        if re.search(r"(?:^|[_\s])(id|code|phone|zip|postal)(?:$|[_\s])", label, re.I):
            continue
        if isinstance(raw, bool) or raw is None:
            continue
        value = str(raw).strip()
        if label and len(value) <= 24 and _NUMBER.fullmatch(value):
            result[label] = Decimal(value)
    return result


def prepare_candidates(candidates):
    """Compute stats once over query-matching rows of each file/region/language.

    Never mix projects, files, languages or geographic scopes. Input is already
    authorized and query-filtered by library.retrieve. This is not a population
    estimate: only observed numeric cells contribute to each field's count.
    """
    groups = defaultdict(list)
    for _, _, evidence in candidates:
        key = (evidence["folder_id"], evidence.get("dataset_file_id", evidence.get("filename")), evidence.get("region"), evidence.get("language"))
        groups[key].append(evidence)
    for records in groups.values():
        columns = defaultdict(list)
        for evidence in records:
            for name, value in numeric_fields(evidence["summary"]).items():
                columns[name].append(value)
        stats = {}
        for name in sorted(columns)[:4]:
            values = columns[name]
            with localcontext() as ctx:
                ctx.prec = 64  # 24-character cells plus the bounded retrieval row count.
                total = sum(values)
                mean = total / len(values)
                stats[name] = {"count": len(values), "sum": str(total),
                               "mean": str(mean.normalize()),
                               "min": str(min(values)), "max": str(max(values))}
        if not stats:
            continue
        prepared = {"scope": "query-matching rows in this file, region and language only",
                    "rows": len(records), "numeric_fields": stats,
                    "revision_digest": hashlib.sha256(json.dumps(sorted((e["id"], e.get("revision")) for e in records)).encode()).hexdigest(),
                    "note": "Unweighted observed cells; not population estimates or verified facts."}
        block = json.dumps(prepared, ensure_ascii=False, separators=(",", ":"))
        # Keep the entire shared summary intact inside existing prompt bounds.
        if len(block) > 1000:
            continue
        for evidence in records:
            evidence["row_excerpt"] = evidence["summary"][:150]
            evidence["dataset_statistics"] = prepared
            evidence["summary"] = "Code-calculated dataset statistics: " + block + "\nSource row excerpt: " + evidence["summary"][:150]
    return len(groups)


def audience_scope(person):
    """All fields used by personal_match; exclude unique names/IDs/interests."""
    keys = ("region", "residence_emirate", "work_emirate", "nationality_group",
            "calendar_memberships", "language", "languages")
    return json.dumps({k: person[k] for k in keys if k in person}, sort_keys=True, ensure_ascii=False)


def compact_selection(selected):
    """Send a shared dataset summary only once in each agent's context."""
    seen, result = set(), []
    for item in selected:
        evidence = dict(item)
        excerpt = evidence.pop("row_excerpt", None)
        stats = evidence.get("dataset_statistics")
        if stats:
            digest = stats["revision_digest"]
            if digest in seen:
                evidence["summary"] = excerpt
                evidence.pop("dataset_statistics", None)
            seen.add(digest)
        result.append(evidence)
    return result
