"""
census scan      -> data/raw/<edition>/*.jsonl        (hashed ids, scored units)
census aggregate -> data/editions/<edition>/census_agents.csv, capabilities.csv, edition.json
census publish   -> site/index.html (all editions)

Example (pilot, ~150 files per GitHub source):
  python -m census.cli scan --edition 2026-11 --max-items 150
  python -m census.cli aggregate --edition 2026-11
  python -m census.cli publish
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import collectors, parsers
from .aggregate import (CSV_COLUMNS, aggregate, capability_rows, sha256_files, write_csv, write_edition_json)
from .manifest import GITHUB_SOURCES, MANIFEST_VERSION, REGISTRY_SOURCES, SIZE_SLICES
from .signals import score

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def _log(msg: str):
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def cmd_scan(a):
    raw = DATA / "raw" / a.edition
    raw.mkdir(parents=True, exist_ok=True)
    gh = collectors.GitHub()
    population = {}
    only = set(a.only.split(",")) if a.only else None

    # population estimates: total_count of each query (one cheap search each)
    for src in GITHUB_SOURCES:
        if only and src["framework"] not in only:
            continue
        r = gh._get(f"{collectors.GH}/search/code", params={"q": src["query"], "per_page": 1})
        if r.status_code == 200:
            population[src["framework"]] = population.get(src["framework"], 0) + r.json().get("total_count", 0)
        time.sleep(gh.sleep_search)
    (raw / "population.json").write_text(json.dumps(population, indent=1))
    _log(f"population estimates: {population}")

    for src in GITHUB_SOURCES:
        if only and src["framework"] not in only:
            continue
        parser = parsers.PARSERS[src["parser"]]
        out = raw / f"github_{src['framework']}_{src['parser']}.jsonl"
        n_files = n_units = 0
        with out.open("w", encoding="utf-8") as f:
            for text, ctx in collectors.github_source(gh, src, a.max_items, SIZE_SLICES, a.keep_ids, a.per_repo_cap):
                n_files += 1
                try:
                    units = parser(text, ctx)
                except Exception as e:  # a parser must never stop the scan
                    _log(f"parse error {src['parser']}: {e}")
                    continue
                for u in units:
                    rec = score(u)
                    rec["id"] = _hash(u.unit_ref)
                    rec["repo_id"] = _hash(ctx.get("repo") or "")   # hashed: allows per-repo caps, names nothing
                    rec["edition"] = a.edition
                    if a.keep_ids:
                        rec["_ref"] = u.unit_ref
                    rec["notes"] = u.notes
                    f.write(json.dumps(rec) + "\n")
                    n_units += 1
        _log(f"{src['framework']}/{src['parser']}: {n_files} files -> {n_units} units ({gh.calls} API calls so far)")

    for reg in REGISTRY_SOURCES:
        if only and reg["source"] not in only:
            continue
        out = raw / f"{reg['source']}_mcp_server.jsonl"
        n = 0
        try:
            if reg["source"] == "npm":
                it = collectors.npm_mcp_servers(a.max_registry)
            elif reg["source"] == "pypi":
                it = collectors.pypi_mcp_servers(a.max_registry)
            else:
                it = collectors.mcp_registry_servers(reg["url"], a.max_registry)
            with out.open("w", encoding="utf-8") as f:
                for meta in it:
                    for u in parsers.parse_mcp_server_meta(meta, reg["source"]):
                        rec = score(u)
                        rec["id"] = _hash(u.unit_ref)
                        rec["edition"] = a.edition
                        if a.keep_ids:
                            rec["_ref"] = u.unit_ref
                        rec["notes"] = u.notes
                        f.write(json.dumps(rec) + "\n")
                        n += 1
        except Exception as e:
            _log(f"{reg['source']} unavailable from this host: {e}")
        _log(f"{reg['source']}: {n} servers")


def cmd_aggregate(a):
    raw = DATA / "raw" / a.edition
    files = [p for p in raw.glob("*.jsonl") if p.stat().st_size > 0]
    records = []
    for p in files:
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
    if a.per_repo_cap:  # sample hygiene: at most N units per repository (needs --keep-ids raw)
        seen: dict[str, int] = {}
        kept = []
        for r in records:
            if r["source"] != "github":
                kept.append(r)
                continue
            repo = r.get("repo_id") or str(r.get("_ref", r["id"])).split(":")[0]
            seen[repo] = seen.get(repo, 0) + 1
            if seen[repo] <= a.per_repo_cap:
                kept.append(r)
        _log(f"per-repo cap {a.per_repo_cap}: {len(records)} -> {len(kept)} units")
        records = kept
    population = json.loads((raw / "population.json").read_text()) if (raw / "population.json").exists() else {}
    raw_sha = sha256_files(files)
    snapshot = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = aggregate(records, a.edition, snapshot, raw_sha, population, exact=a.exact)
    cap = capability_rows(records, a.edition)
    ed = DATA / "editions" / a.edition
    ed.mkdir(parents=True, exist_ok=True)
    write_csv(ed / "census_agents.csv", rows, CSV_COLUMNS)
    write_csv(ed / "capabilities.csv", cap, ["edition", "source", "framework", "kind", "access_class", "tools"])
    meta = {"edition": a.edition, "snapshot_utc": snapshot, "units": len(records), "raw_sha256": raw_sha,
            "manifest_version": MANIFEST_VERSION, "population_estimate": population,
            "sources_run": sorted({r["source"] for r in records})}
    write_edition_json(ed / "edition.json", rows, cap, meta)
    _log(f"edition {a.edition}: {len(records)} units, {len(rows)} rows, sha256 {raw_sha[:12]}…")
    for r in rows:
        if r["framework"] in ("all_agents",) or r["kind"] == "agent":
            _log(f"  {r['framework']:<24} n={r['units']:<6} consequential={r['consequential']:<6} "
                 f"outrun={r['outrun_rate']}% strict={r['outrun_strict_rate']}% score={r['charter_score_median']}")


def cmd_publish(a):
    from .publish import build_site
    out = build_site(DATA / "editions", ROOT / "site")
    _log(f"wrote {out}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="census")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("--edition", required=True, help="YYYY-MM")
    s.add_argument("--max-items", type=int, default=int(os.environ.get("CENSUS_MAX_ITEMS", "12000")),
                   help="max files per GitHub source (12 slices x 1000)")
    s.add_argument("--max-registry", type=int, default=int(os.environ.get("CENSUS_MAX_REGISTRY", "5000")))
    s.add_argument("--only", default="", help="comma list of frameworks/sources to run")
    s.add_argument("--keep-ids", action="store_true", help="keep repo/path in raw (internal use only)")
    s.add_argument("--per-repo-cap", type=int, default=int(os.environ.get("CENSUS_PER_REPO_CAP", "0")),
                   help="max files per repository (0 = no cap); use for samples")
    s.set_defaults(fn=cmd_scan)
    g = sub.add_parser("aggregate")
    g.add_argument("--edition", required=True)
    g.add_argument("--exact", action="store_true", help="do not suppress counts <5 (internal)")
    g.add_argument("--per-repo-cap", type=int, default=0, help="sample hygiene: max units per repository (uses hashed repo_id)")
    g.set_defaults(fn=cmd_aggregate)
    p = sub.add_parser("publish")
    p.set_defaults(fn=cmd_publish)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
