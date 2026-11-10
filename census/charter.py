"""
Charter Score for a charter file (charter.json), on the same pillar weights as
the census scan (signals.PILLAR_MAX: 20/10/15/15/10/5/15/10).

The scan scores what it can infer from a public agent definition. A charter
states the terms directly, so each pillar here reads the charter's own fields.
Where a tier exists in both, it is worth the same points in both:

  pillar          scan evidence                     charter evidence (this module)
  1 owner         declared 20 / group only 4        user: identity 20 / role or group 4
  2 recipient     named in text 6                   named 6 / named with backup 10
  3 approval      not consequential, or held: 15    not required, or named: 15
  4 scope         deny list 15 / PROHIBIT text 8   an Enforced item 15 / Instructed only 8
  5 systems       classes declared 10 / listed 6    classes + every write tool's reversal owner 10 / classes 6
  6 inputs        INPUTS text, or not consequential inputs stated, or not consequential: 5
  7 escalation    explicit hold 15 / text 8         four minimum triggers 15 / some 8
  8 constraints   unheld irreversible 0 / limits 10 irreversible not held 0 / limits 10 / default 5

A pillar is "pass" at full points, "fail" at 0 and "partial" in between.

This module is imported, not copied, by almma-ai/charter-registry, so a score
means the same in the census, the registry and the badge.
"""
from __future__ import annotations

import hashlib
from typing import Any

from .signals import PILLAR_KEYS, PILLAR_MAX

SCORER_ID = "census.charter.score_charter/1"

PILLAR_LABELS = ["Owner", "Escalation recipient", "Approval authority", "Scope (never-do)",
                 "Systems and permissions", "Inputs and outputs", "Escalation rules", "Execution constraints"]

MIN_TRIGGERS = ["out_of_scope", "never_do_match", "missing_required_input", "irreversible_action"]
# An irreversible action must wait for a person (SPEC pillar 8). These actions do.
HOLDING_ACTIONS = {"hand_off", "ask_requester", "hold_for_approval"}
LIMIT_FIELDS = ["max_tool_calls_per_run", "max_spend_per_run", "rate_limit_per_hour"]


# JSON Schema per spec version, from almma-ai/delegation-charter, pinned to the
# commit that added it, so a later edit there cannot change a past result.
SCHEMA_URLS = {
    "delegation-charter/0.1.2":
        "https://raw.githubusercontent.com/almma-ai/delegation-charter/cc625c9b1eb040bf5542a198f2dc680f7df4807b/schema/charter-0.1.2.schema.json",
}


def load_schema(spec: str, path: str | None = None) -> dict:
    """The JSON Schema for a charter's spec version: from a local file if given,
    otherwise fetched from delegation-charter (nothing is sent, only fetched)."""
    import json
    import urllib.request
    if path:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    url = SCHEMA_URLS.get(spec)
    if not url:
        raise ValueError(f"no schema for spec {spec!r}; known: {', '.join(SCHEMA_URLS)}")
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read())


def validate(charter: dict, schema: dict) -> list[str]:
    """Schema errors as readable lines; empty when the charter is valid."""
    from jsonschema import Draft202012Validator, FormatChecker
    v = Draft202012Validator(schema, format_checker=FormatChecker())
    out = []
    for e in sorted(v.iter_errors(charter), key=lambda e: [str(p) for p in e.absolute_path]):
        where = "/".join(str(p) for p in e.absolute_path) or "(top level)"
        msg = e.message
        if e.validator == "contains" and where == "escalation_rules":
            msg = "needs a rule with an action for each minimum trigger: " + ", ".join(MIN_TRIGGERS)
        elif len(msg) > 200:
            msg = msg[:200] + "…"
        out.append(f"{where}: {msg}")
    return out


def charter_hash(raw: bytes) -> str:
    """SHA-256 of the charter file exactly as stored."""
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _identity(obj: Any) -> str | None:
    if isinstance(obj, dict):
        v = obj.get("identity")
        return v if isinstance(v, str) and ":" in v else None
    return None


def result(points: int, maximum: int) -> str:
    return "pass" if points >= maximum else ("fail" if points <= 0 else "partial")


def score_charter(c: dict) -> dict:
    """Score one charter (a parsed charter.json). Returns the total, per-pillar
    points and results, and the reason for each pillar's points."""
    systems = c.get("systems") if isinstance(c.get("systems"), list) else None
    access = [s.get("access") for s in (systems or []) if isinstance(s, dict)]
    consequential = any(a in ("write", "irreversible") for a in access)
    has_irreversible = "irreversible" in access
    rules = [r for r in (c.get("escalation_rules") or []) if isinstance(r, dict)]
    rule_for = {r.get("trigger"): r for r in rules if r.get("action")}
    constraints = c.get("constraints") if isinstance(c.get("constraints"), dict) else {}
    pts: list[int] = []
    why: list[str] = []

    # 1 Owner (20)
    owner = _identity(c.get("owner"))
    if owner and owner.startswith("user:"):
        pts.append(20); why.append("Owner is a named person.")
    elif owner:
        pts.append(4); why.append("Owner is a role or group, not a person.")
    else:
        pts.append(0); why.append("No owner named.")

    # 2 Escalation recipient (10)
    er = c.get("escalation_recipient") if isinstance(c.get("escalation_recipient"), dict) else {}
    if _identity(er) and isinstance(er.get("backup"), str) and er.get("backup"):
        pts.append(10); why.append("Recipient named, with a backup.")
    elif _identity(er):
        pts.append(6); why.append("Recipient named; no backup.")
    else:
        pts.append(0); why.append("No escalation recipient named.")

    # 3 Approval authority (15): required when the agent writes or acts irreversibly
    approver = _identity(c.get("approval_authority"))
    activation = c.get("activation") if isinstance(c.get("activation"), dict) else {}
    if not consequential:
        pts.append(15); why.append("Read-only: approval not required." + (" Approver named." if approver else ""))
    elif approver and activation.get("type") != "self_declared":
        pts.append(15); why.append("Write or irreversible tools; approval authority named.")
    elif approver:
        pts.append(0); why.append("Write or irreversible tools, but self-declared rather than approved.")
    else:
        pts.append(0); why.append("Write or irreversible tools and no approval authority.")

    # 4 Scope never-do (15)
    scope = c.get("scope") if isinstance(c.get("scope"), dict) else {}
    nd = [i for i in (scope.get("never_do") or []) if isinstance(i, dict) and i.get("item")]
    enforced = [i for i in nd if i.get("enforcement") == "enforced" and i.get("tool")]
    if enforced:
        pts.append(15); why.append(f"{len(nd)} never-do item(s), {len(enforced)} enforced at a tool.")
    elif nd:
        pts.append(8); why.append(f"{len(nd)} never-do item(s), all instructed only.")
    else:
        pts.append(0); why.append("Never-do list is empty.")

    # 5 Systems and permissions (10)
    if systems is None:
        pts.append(0); why.append("Systems not listed.")
    else:
        classed = all(a in ("read", "write", "irreversible") for a in access) and len(access) == len(systems)
        writes = [s for s in systems if isinstance(s, dict) and s.get("access") == "write"]
        unowned = [s for s in writes if not (isinstance(s.get("reversal"), dict) and s["reversal"].get("owner"))]
        if classed and not unowned:
            pts.append(10); why.append(f"{len(systems)} system(s), each classed" + ("; every write tool has a reversal owner." if writes else "."))
        elif classed:
            pts.append(6); why.append(f"{len(unowned)} write tool(s) without a reversal owner.")
        else:
            pts.append(0); why.append("Some systems have no access class.")

    # 6 Inputs and outputs (5)
    inputs = c.get("inputs")
    if isinstance(inputs, dict) and isinstance(inputs.get("required"), list):
        pts.append(5); why.append("Required inputs stated." if inputs["required"] else "States that no input is required.")
    elif not consequential:
        pts.append(5); why.append("Read-only: platform default applies.")
    else:
        pts.append(0); why.append("Required inputs not stated.")

    # 7 Escalation rules (15)
    covered = [t for t in MIN_TRIGGERS if t in rule_for]
    if len(covered) == len(MIN_TRIGGERS):
        pts.append(15); why.append("All four minimum triggers have an action" + (", plus trigger 5." if "action_found_wrong" in rule_for else "."))
    elif covered:
        pts.append(8); why.append(f"{len(covered)} of 4 minimum triggers covered.")
    else:
        pts.append(0); why.append("No escalation rules.")

    # 8 Execution constraints (10)
    irr_rule = rule_for.get("irreversible_action", {}).get("action")
    rule_holds = irr_rule is None or irr_rule in HOLDING_ACTIONS
    stated = constraints.get("irreversible_actions") == "require_approval"
    limits = [f for f in LIMIT_FIELDS if constraints.get(f) is not None]
    if not rule_holds:
        pts.append(0); why.append(f"Trigger 4 action '{irr_rule}' lets an irreversible action go ahead without a person.")
    elif has_irreversible and not stated:
        pts.append(0); why.append("Irreversible tools, and the constraints do not require approval.")
    elif limits:
        pts.append(10); why.append("Irreversible actions need approval; limits set: " + ", ".join(limits) + ".")
    else:
        pts.append(5); why.append("Irreversible actions need approval; no rate or spend limit (platform default).")

    pillars = [
        {"n": i + 1, "key": PILLAR_KEYS[i], "label": PILLAR_LABELS[i], "points": pts[i],
         "max": PILLAR_MAX[i], "result": result(pts[i], PILLAR_MAX[i]), "reason": why[i]}
        for i in range(8)
    ]
    return {"scorer": SCORER_ID, "charter_score": sum(pts), "pillars": pillars}
