"""
Build site/index.html from every data/editions/<edition>/edition.json.
One number, one table, one chart, the method, the downloads. No names anywhere.
"""
from __future__ import annotations

import html
import json
from pathlib import Path

LABELS = {
    "all_agents": "All agents",
    "claude_code_subagent": "Claude Code subagents",
    "copilot_custom_agent": "GitHub Copilot custom agents",
    "crewai": "CrewAI crews",
    "langgraph": "LangGraph graphs",
    "a2a_agent_card": "A2A agent cards",
    "mcp_client_config": "MCP client configs",
    "librechat_config": "LibreChat deployments",
    "mcp_server": "MCP servers",
}
PILLARS = ["Owner", "Escalation recipient", "Approval authority", "Scope (never-do)", "Systems",
           "Inputs", "Escalation rules", "Constraints"]


def _fmt(v):
    if v == "" or v is None:
        return "—"
    return html.escape(str(v))


def build_site(editions_dir: Path, site_dir: Path) -> Path:
    eds = []
    for p in sorted(editions_dir.glob("*/edition.json")):
        eds.append(json.loads(p.read_text(encoding="utf-8")))
    if not eds:
        raise SystemExit("no editions")
    cur = eds[-1]
    rows = cur["rows"]
    allrow = next((r for r in rows if r["framework"] == "all_agents"), None)
    agent_rows = [r for r in rows if r["kind"] == "agent" and r["framework"] != "all_agents"]
    supply_rows = [r for r in rows if r["kind"] != "agent"]
    series = [(e["meta"]["edition"], next((r["outrun_rate"] for r in e["rows"] if r["framework"] == "all_agents"), ""))
              for e in eds]
    pop = cur["meta"].get("population_estimate") or {}
    pop_total = sum(v for k, v in pop.items() if k in {r["framework"] for r in agent_rows})

    def pillar_bars(r):
        keys = ["owner", "recipient", "approval", "scope", "systems", "inputs", "escalation", "constraints"]
        out = []
        for name, k in zip(PILLARS, keys):
            v = r.get(f"pillar_{k}_avg")
            w = float(v) if v not in ("", None) else 0
            out.append(f'<div class="bar"><span>{html.escape(name)}</span><i style="width:{w:.0f}%"></i><b>{_fmt(v)}%</b></div>')
        return "\n".join(out)

    table = "\n".join(
        f"<tr><td>{html.escape(LABELS.get(r['framework'], r['framework']))}</td>"
        f"<td class=n>{_fmt(r['units'])}</td><td class=n>{_fmt(r['consequential'])}</td>"
        f"<td class=n><strong>{_fmt(r['outrun_rate'])}%</strong></td><td class=n>{_fmt(r['outrun_strict_rate'])}%</td>"
        f"<td class=n>{_fmt(r['owner_declared_rate'])}%</td><td class=n>{_fmt(r['hold_rate'])}%</td>"
        f"<td class=n>{_fmt(r['prohibit_rate'])}%</td><td class=n>{_fmt(r['charter_score_median'])}</td></tr>"
        for r in sorted(agent_rows, key=lambda r: -float(r['units'] if isinstance(r['units'], int) else 0))
    )
    supply = "\n".join(
        f"<tr><td>{html.escape(LABELS.get(r['framework'], r['framework']))} ({html.escape(r['source'])})</td>"
        f"<td class=n>{_fmt(r['units'])}</td><td class=n>{_fmt(r['max_access_irreversible'])}</td>"
        f"<td class=n>{_fmt(r['max_access_write'])}</td><td class=n>{_fmt(r['max_access_read'])}</td>"
        f"<td class=n>{_fmt(r['owner_declared_rate'])}%</td></tr>"
        for r in supply_rows
    )
    pts = [(i, float(v)) for i, (_, v) in enumerate(series) if v not in ("", None)]
    if len(pts) >= 2:
        W, H = 600, 160
        xs = [20 + i * (W - 40) / max(1, len(series) - 1) for i, _ in pts]
        ys = [H - 20 - (v / 100) * (H - 40) for _, v in pts]
        poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
        chart = (f'<svg viewBox="0 0 {W} {H}" class="chart"><polyline points="{poly}"/>' +
                 "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4"/><text x="{x:.1f}" y="{H-4}">{html.escape(series[i][0])}</text>'
                         for (i, _), x, y in zip(pts, xs, ys)) + "</svg>")
    else:
        chart = '<p class="muted">The series chart appears from the second edition.</p>'

    edition = cur["meta"]["edition"]
    n_ed = len(eds)
    big = _fmt(allrow["outrun_rate"]) if allrow else "—"
    big_strict = _fmt(allrow["outrun_strict_rate"]) if allrow else "—"
    n_agents = _fmt(allrow["units"]) if allrow else "—"
    n_cons = _fmt(allrow["consequential"]) if allrow else "—"
    score_med = _fmt(allrow["charter_score_median"]) if allrow else "—"

    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Agents Outrun Review · Edition {n_ed:03d} · {html.escape(edition)}</title>
<style>
:root{{--ink:#141414;--mute:#6b6b6b;--line:#e6e6e6;--acc:#b3261e;--bg:#fff}}
*{{box-sizing:border-box}}body{{margin:0;font:16px/1.5 Georgia,"Times New Roman",serif;color:var(--ink);background:var(--bg)}}
main{{max-width:880px;margin:0 auto;padding:48px 20px 80px}}
header{{display:flex;justify-content:space-between;align-items:baseline;border-bottom:1px solid var(--ink);padding-bottom:8px}}
header h1{{font-size:18px;letter-spacing:.08em;text-transform:uppercase;margin:0;font-weight:600}}
header span{{color:var(--mute);font-size:14px}}
.hero{{padding:56px 0 24px}}
.hero .num{{font-size:clamp(96px,22vw,220px);line-height:.9;font-weight:700;letter-spacing:-.04em;color:var(--acc)}}
.hero .num small{{font-size:.35em;letter-spacing:0;color:var(--ink)}}
.hero p.lede{{font-size:22px;max-width:40ch;margin:18px 0 0}}
.kv{{display:flex;gap:32px;flex-wrap:wrap;margin:20px 0 0;color:var(--mute);font-size:15px}}
.kv b{{color:var(--ink);font-family:ui-monospace,Menlo,monospace}}
h2{{font-size:14px;letter-spacing:.08em;text-transform:uppercase;margin:48px 0 12px;color:var(--mute);font-weight:600}}
table{{width:100%;border-collapse:collapse;font-size:15px}}th,td{{padding:8px 6px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}
th{{font-weight:600;font-size:13px;color:var(--mute)}}td.n,th.n{{text-align:right;font-family:ui-monospace,Menlo,monospace}}
.bars{{display:grid;gap:6px;max-width:560px}}.bar{{display:grid;grid-template-columns:170px 1fr 56px;align-items:center;gap:10px;font-size:14px}}
.bar i{{display:block;height:10px;background:var(--ink)}}.bar b{{font-family:ui-monospace,Menlo,monospace;font-weight:500;text-align:right}}
.chart{{width:100%;max-width:600px;height:auto}}.chart polyline{{fill:none;stroke:var(--acc);stroke-width:2}}.chart circle{{fill:var(--acc)}}
.chart text{{font:11px ui-monospace,Menlo,monospace;fill:var(--mute);text-anchor:middle}}
.muted{{color:var(--mute)}}code{{font-family:ui-monospace,Menlo,monospace;font-size:14px;background:#f5f5f5;padding:1px 5px}}
pre{{background:#f5f5f5;padding:12px;overflow:auto;font-size:13px}}
footer{{margin-top:64px;border-top:1px solid var(--line);padding-top:16px;color:var(--mute);font-size:14px}}
.badge{{display:inline-block;border:1px solid var(--ink);padding:2px 8px;font:12px ui-monospace,Menlo,monospace}}
</style></head><body><main>
<header><h1>Agents Outrun Review</h1><span>Edition {n_ed:03d} · {html.escape(edition)} · monthly index</span></header>

<section class="hero">
  <div class="num">{big}<small>%</small></div>
  <p class="lede">of public AI agents that can write, run code or take irreversible actions name no accountable person and have no hold before they act.</p>
  <div class="kv"><span>agents scored <b>{n_agents}</b></span><span>with consequential capability <b>{n_cons}</b></span>
  <span>strict rate (explicit holds only) <b>{big_strict}%</b></span><span>median Charter Score <b>{score_med}</b>/100</span>
  <span>public population this month <b>{pop_total:,}</b> definitions</span></div>
</section>

<h2>Series</h2>
{chart}

<h2>By framework · categories, never names</h2>
<table><thead><tr><th>Framework</th><th class=n>Scored</th><th class=n>Consequential</th><th class=n>Outrun rate</th><th class=n>Strict</th>
<th class=n>Owner declared</th><th class=n>Hold present</th><th class=n>Never-do stated</th><th class=n>Score (median)</th></tr></thead>
<tbody>{table}</tbody></table>
<p class="muted">Outrun rate = share of agents with write, code or irreversible capability that have neither a declared accountable person nor a hold before acting. Strict counts only explicit holds (interrupts, human_input, approval policy), not platform defaults. Counts from 1 to 4 are shown as &lt;5.</p>

<h2>The eight pillars · average coverage, all agents</h2>
<div class="bars">{pillar_bars(allrow) if allrow else ''}</div>

<h2>Capability supply · MCP servers and client configurations</h2>
<table><thead><tr><th>Source</th><th class=n>Units</th><th class=n>Irreversible-class</th><th class=n>Write-class</th><th class=n>Read-class</th><th class=n>Author named</th></tr></thead>
<tbody>{supply}</tbody></table>

<h2>Get out of this number</h2>
<p>Add a charter and the badge. A <code>charter.json</code> following the <a href="https://github.com/almma-ai/delegation-charter">Delegation Charter Specification</a> moves an agent from scanned to self-certified, and the badge <span class="badge">charter v1.0 · score 00</span> enters it in the index by choice.</p>

<h2>Method</h2>
<p>Every month a script runs the open-source diagnostic against agent definitions that are already public: GitHub code search for each framework's configuration file, the MCP registry, npm and PyPI. Each file becomes one or more agents by a fixed unit rule. Each agent is read for the eight pillars of the Delegation Charter. Structural facts (tools held, deny lists, interrupts, CODEOWNERS) are exact; instruction-text patterns are English-only and reported as upper bounds. No project, repository, maintainer or user is named; identifiers are hashed before storage.</p>
<p>Reproduce this edition: <code>python -m census.cli scan --edition {html.escape(edition)} &amp;&amp; python -m census.cli aggregate --edition {html.escape(edition)}</code>.
Raw snapshot SHA-256: <code>{html.escape(cur['meta']['raw_sha256'])}</code>. Manifest v{html.escape(cur['meta']['manifest_version'])}.</p>
<p>Downloads: <a href="../data/editions/{html.escape(edition)}/census_agents.csv">census_agents.csv</a> · <a href="../data/editions/{html.escape(edition)}/capabilities.csv">capabilities.csv</a> · <a href="../data/editions/{html.escape(edition)}/edition.json">edition.json</a></p>

<footer>Agents Outrun Review is published by Almma.AI under CC BY 4.0. Editions are append-only; each publishes the hash of its snapshot so no edition can be rewritten quietly. Prior work: <em>Agents Outrun Review: A Read-Only Audit and Multi-Site Protocol for Delegated AI Agents</em> (SSRN 7599098).</footer>
</main></body></html>
"""
    site_dir.mkdir(parents=True, exist_ok=True)
    out = site_dir / "index.html"
    out.write_text(page, encoding="utf-8")
    return out
