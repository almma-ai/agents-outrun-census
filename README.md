# Agents Outrun Census

The instrument behind the **Agents Outrun Review**: a monthly, unattended scan of
every public AI-agent definition we can reach, read against the eight pillars of the
[Delegation Charter Specification](https://github.com/almma-ai/delegation-charter),
published as counts by category. No project, repository or person is ever named.

```
python -m census.cli scan      --edition 2026-12          # GitHub + npm + PyPI + MCP registry
python -m census.cli aggregate --edition 2026-12          # -> data/editions/2026-12/*.csv, edition.json
python -m census.cli publish                              # -> site/index.html
```

`GITHUB_TOKEN` is required (code search is authenticated). The GitHub Actions workflow
runs the three commands on the 1st of each month, commits the edition and deploys the page.

## What is counted

| Framework | Found by | Unit |
| --- | --- | --- |
| Claude Code subagents | `path:.claude/agents extension:md` | one `.md` = one agent |
| GitHub Copilot custom agents | `path:.github/agents extension:md` | one `.md` = one agent |
| CrewAI | `filename:crew.py crewai`, `filename:agents.yaml crewai` | one `Agent(...)` / YAML entry = one agent |
| LangGraph | `filename:langgraph.json` (+ the graph module) | one entry in `graphs{}` = one agent |
| A2A agent cards | `filename:agent.json path:.well-known` | one card = one agent |
| MCP client configs | `claude_desktop_config.json`, `.mcp.json`, `librechat.yaml` | one config = one capability bundle |
| MCP servers | npm `keywords:mcp`, PyPI names matching `mcp-server`, registry.modelcontextprotocol.io | one package = one server |

Agents are the population for the headline. MCP servers and client configs are
"capability supply" and are reported separately.

## What is read, per agent

**Structural (exact, language-independent)**: tools held and their inferred access class
(read / write / code / irreversible, verb list from `librechat-charter-diagnostic`);
inherits-all-tools; external reach; a hold before acting (`interrupt_before`, `human_input`,
`permissionMode`, tool-approval policy) and whether it is explicit or a platform default;
a deny list; rate/spend/turn limits; owner evidence (owner/contact field, CODEOWNERS
naming a person, individual-owned repository, organisation only); `charter.json` and badge.

**Instructed (English patterns, upper bounds)**: ESCALATE, PROHIBIT, SCOPE, RECIPIENT,
INPUTS and the irreversible-action trigger, verbatim from `agent-governance-check`.

## Headline metric: the Outrun Rate

> Share of agents with write, code or irreversible capability that have **neither a
> declared accountable person nor a hold before acting**.

`outrun_strict_rate` counts only explicit holds. `irreversible_unheld_rate` is the
pillar-8 contradiction. Both are in every CSV row.

## Charter Score v0.1 (0–100)

| Pillar | Max | Evidence |
| --- | --- | --- |
| 1 Owner | 20 | declared 20 · individual on record 8 · group only 4 · none 0 |
| 2 Escalation recipient | 10 | named recipient / contact in text 6 |
| 3 Approval authority | 15 | 15 unless consequential and unheld |
| 4 Scope never-do | 15 | deny list 15 · PROHIBIT text 8 |
| 5 Systems | 10 | no tools or classes declared 10 · tools listed 6 · inherits all 0 |
| 6 Inputs | 5 | INPUTS text, or not consequential |
| 7 Escalation rules | 15 | explicit hold 15 · ESCALATE text 8 |
| 8 Constraints | 10 | irreversible unheld 0 · limits set 10 · default 5 |

## Charter Score for a charter file

The same eight weights score a `charter.json` directly, for the
[Charter Registry](https://github.com/almma-ai/charter-registry). `census/charter.py`
reads the charter's own fields; where a tier exists in both the scan and the charter
(a named recipient 6, instructed-only never-do 8, unheld irreversible actions 0,
platform-default constraints 5), it is worth the same points. The full table is at
the top of `census/charter.py`. A pillar is pass at full points, fail at 0, partial between.

```
pip install "agents-outrun-census @ git+https://github.com/almma-ai/agents-outrun-census@v0.2.0"
census check charter.json                  # schema check and score, nothing signed
census keygen --product product.yml        # Ed25519 key in ~/.config/charter-registry/keys/
census sign   --product product.yml        # attestation.json next to charter.json
```

Everything runs locally; the only network call fetches the charter JSON Schema from
`almma-ai/delegation-charter` (pass `--schema <file>` to work offline). The registry
imports `census.charter.score_charter` and `census.attest.verify`, never a copy.

## Privacy and reproducibility

Identifiers are SHA-256 hashed before they reach disk. Published counts from 1 to 4 appear
as `<5`. Each edition records the manifest version, the tool version and the SHA-256 of its
raw snapshot; editions are append-only.

## Layout

```
census/manifest.py    queries, unit rules, size slices        (versioned instrument)
census/collectors.py  GitHub code search + blobs, npm, PyPI, MCP registry
census/parsers.py     file -> AgentUnit(s) per framework
census/signals.py     patterns, access classes, Charter Score, pillar weights
census/charter.py     Charter Score for a charter.json, schema check
census/attest.py      signed attestations (keygen, sign, verify)
census/aggregate.py   CSV rows, suppression, snapshot hash
census/publish.py     site/index.html
data/raw/<edition>/   scored units, hashed ids (jsonl) + population.json
data/editions/<ed>/   census_agents.csv, capabilities.csv, edition.json
```

Licence: code Apache-2.0, data CC BY 4.0.
