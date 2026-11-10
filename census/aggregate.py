"""
Aggregate scored units into the edition's CSV rows. Counts only, never names.
"""
from __future__ import annotations

import csv
import hashlib
import json
import statistics
from collections import defaultdict
from pathlib import Path

from . import __version__ as TOOL_VERSION
from .manifest import MANIFEST_VERSION, SUPPRESS_BELOW
from .signals import PILLAR_MAX

COUNT_FIELDS = [
    "units", "with_instructions", "with_tools", "tools_all", "consequential", "external_reach",
    "max_access_read", "max_access_write", "max_access_code", "max_access_irreversible", "max_access_unknown",
    "owner_declared", "owner_on_record", "owner_group_only", "owner_none",
    "hold_structural", "deny_structural", "limits_structural", "access_declared",
    "charter_json", "charter_badge",
    "escalate_instructed", "recipient_instructed", "prohibit_instructed", "scope_instructed",
    "inputs_instructed", "irreversible_trigger_instructed",
    "capability_without_scope", "irreversible_unheld", "outrun", "outrun_strict",
]
RATE_FIELDS = ["outrun_rate", "outrun_strict_rate", "irreversible_unheld_rate", "owner_declared_rate",
               "hold_rate", "prohibit_rate", "escalate_rate", "capability_without_scope_rate"]
STAT_FIELDS = ["instructions_chars_median", "charter_score_median", "charter_score_p25", "charter_score_p75",
               "pillar_owner_avg", "pillar_recipient_avg", "pillar_approval_avg", "pillar_scope_avg",
               "pillar_systems_avg", "pillar_inputs_avg", "pillar_escalation_avg", "pillar_constraints_avg"]

CSV_COLUMNS = (["edition", "snapshot_utc", "source", "framework", "kind"] + COUNT_FIELDS + RATE_FIELDS
               + STAT_FIELDS + ["sampled", "population_estimate", "tool_version", "manifest_version", "raw_sha256"])


def _pct(n: int, d: int) -> float | str:
    return round(100.0 * n / d, 1) if d else ""


def _median(xs):
    return round(statistics.median(xs), 1) if xs else ""


def _q(xs, q):
    if not xs:
        return ""
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    f, c = int(k), min(int(k) + 1, len(xs) - 1)
    return round(xs[f] + (xs[c] - xs[f]) * (k - f), 1)


def suppress(v):
    if isinstance(v, int) and 0 < v < SUPPRESS_BELOW:
        return "<5"
    return v


def aggregate(records: list[dict], edition: str, snapshot_utc: str, raw_sha: str,
              population: dict | None = None, exact: bool = False) -> list[dict]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in records:
        groups[(r["source"], r["framework"], r["kind"])].append(r)
    # an "all agents" row across frameworks
    agents = [r for r in records if r["kind"] == "agent"]
    if agents:
        groups[("all", "all_agents", "agent")] = agents
    rows = []
    for (source, framework, kind), rs in sorted(groups.items()):
        n = len(rs)
        c = {k: 0 for k in COUNT_FIELDS}
        c["units"] = n
        for r in rs:
            for k in ("has_instructions", "has_tools", "tools_all", "consequential", "external_reach",
                      "owner_declared", "owner_on_record", "owner_group_only", "hold_structural", "deny_structural",
                      "limits_structural", "access_declared", "charter_json", "charter_badge",
                      "escalate_instructed", "recipient_instructed", "prohibit_instructed", "scope_instructed",
                      "inputs_instructed", "irreversible_trigger_instructed", "capability_without_scope",
                      "irreversible_unheld", "outrun"):
                key = {"has_instructions": "with_instructions", "has_tools": "with_tools"}.get(k, k)
                if r.get(k):
                    c[key] += 1
            c[f"max_access_{r['max_access'] if r['max_access'] != 'none' else 'unknown'}"] += 1 if r["max_access"] != "none" else 0
            if not (r["owner_declared"] or r["owner_on_record"] or r["owner_group_only"]):
                c["owner_none"] += 1
            # strict: platform-default holds do not count
            if r.get("consequential") and not r.get("owner_declared") and not r.get("hold_explicit"):
                c["outrun_strict"] += 1
        cons = c["consequential"]
        rates = {
            "outrun_rate": _pct(c["outrun"], cons),
            "outrun_strict_rate": _pct(c["outrun_strict"], cons),
            "irreversible_unheld_rate": _pct(c["irreversible_unheld"], n),
            "owner_declared_rate": _pct(c["owner_declared"], n),
            "hold_rate": _pct(c["hold_structural"], n),
            "prohibit_rate": _pct(c["prohibit_instructed"], n),
            "escalate_rate": _pct(c["escalate_instructed"], n),
            "capability_without_scope_rate": _pct(c["capability_without_scope"], c["with_tools"]),
        }
        scores = [r["charter_score"] for r in rs]
        pil = [[r["pillars"][i] for r in rs] for i in range(8)]
        stats = {
            "instructions_chars_median": _median([r["instructions_chars"] for r in rs]),
            "charter_score_median": _median(scores),
            "charter_score_p25": _q(scores, 0.25),
            "charter_score_p75": _q(scores, 0.75),
        }
        for i, name in enumerate(["owner", "recipient", "approval", "scope", "systems", "inputs", "escalation", "constraints"]):
            stats[f"pillar_{name}_avg"] = round(100.0 * statistics.mean(pil[i]) / PILLAR_MAX[i], 1) if pil[i] else ""
        row = {"edition": edition, "snapshot_utc": snapshot_utc, "source": source, "framework": framework, "kind": kind}
        row.update({k: (c[k] if exact else suppress(c[k])) for k in COUNT_FIELDS})
        row.update(rates)
        row.update(stats)
        row["sampled"] = n
        row["population_estimate"] = (population or {}).get(framework, "")
        row["tool_version"] = TOOL_VERSION
        row["manifest_version"] = MANIFEST_VERSION
        row["raw_sha256"] = raw_sha
        rows.append(row)
    return rows


def capability_rows(records: list[dict], edition: str) -> list[dict]:
    out = defaultdict(int)
    for r in records:
        for cls in ("read", "write", "code", "irreversible", "unknown"):
            out[(r["source"], r["framework"], r["kind"], cls)] += r.get(f"access_{cls}", 0)
    return [{"edition": edition, "source": s, "framework": f, "kind": k, "access_class": cls, "tools": n}
            for (s, f, k, cls), n in sorted(out.items())]


def sha256_files(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def write_csv(path: Path, rows: list[dict], columns: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def write_edition_json(path: Path, rows: list[dict], cap_rows: list[dict], meta: dict):
    path.write_text(json.dumps({"meta": meta, "rows": rows, "capabilities": cap_rows}, indent=1), encoding="utf-8")
