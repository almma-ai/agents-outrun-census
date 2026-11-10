"""
Charter signals read from a public agent definition.

Patterns are copied from almma-ai/agent-governance-check (CODEBOOK.md) and
almma-ai/librechat-charter-diagnostic (lib/text.js, lib/tools.js) so census
numbers are comparable with the 3,478-agent audit and the SSRN paper.

Two tiers, kept apart everywhere downstream:
  structural  - exact facts about configuration (tools held, deny lists,
                interrupts, CODEOWNERS). Language-independent.
  instructed  - English keyword patterns over instruction text. Upper bound.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict

# ---------------------------------------------------------------- text tier
ESCALATE = re.compile(
    r"escalat|ask (the )?(user|human|me)|check with|confirm with|defer to|"
    r"if (you are |you'?re )?(unsure|uncertain)|do not (guess|assume)|human review|"
    r"approval|sign[- ]?off|hand (it )?off|flag (it|this|for)",
    re.I,
)
PROHIBIT = re.compile(
    r"\bnever\b|\bdo not\b|\bdon'?t\b|must not|shall not|under no circumstance|"
    r"refuse|avoid|out of scope|not permitted|prohibited",
    re.I,
)
SCOPE = re.compile(
    r"\byou (are|act as|will)\b|\brole\b|\bscope\b|\btask\b|\bonly\b|\bobjective\b|\bpurpose\b",
    re.I,
)
RECIPIENT = re.compile(
    r"\b(escalat\w* to|hand (it )?off to|forward (it )?to|refer (them|the user|it) to|contact|"
    r"reach out to|notify|route (it )?to)\s+(?:the\s+|our\s+|a\s+|an\s+)?"
    r"([A-Z][\w.-]+|[\w.+-]+@[\w-]+\.[\w.]+|(?:\w+\s){0,2}(team|desk|manager|lead|owner|officer|"
    r"supervisor|admin|support|department|counsel))",
    re.I,
)
INPUTS = re.compile(
    r"\b(required (input|field|information)s?|you (must|need to) (receive|be given|have)|"
    r"the user must provide|requires? (the|a|an) [\w ]{1,30} (to|before))\b",
    re.I,
)
IRREVERSIBLE_TRIGGER = re.compile(
    r"((before|prior to) (you )?(send|delet|submit|publish|book|pay|charg|transfer|execut|commit|post|cancel|confirm)"
    r"\w*[^.]{0,60}(confirm|approv|ask|check|permission)|(confirm|approval|approve|permission|sign[- ]?off)[^.]{0,60}"
    r"(before|prior to) (you )?(send|delet|submit|publish|book|pay|charg|transfer|execut|commit|post|cancel)|"
    r"never (send|delete|submit|publish|pay|charge|transfer|execute|cancel)\w* (anything |any \w+ )?without)",
    re.I,
)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")

# ---------------------------------------------------------------- tool tier
# External reach, matched against tool names (CODEBOOK: EXTERNAL).
EXTERNAL = re.compile(
    r"search|crawl|sitemap|news|trending|web|browser|fetch|tavily|traversaal|google|youtube|"
    r"wolfram|weather|dalle|image_gen|flux|stable-diffusion|_action_|http|slack|gmail|email|"
    r"twitter|linkedin|stripe|paypal|github|jira|notion|salesforce|hubspot|sms|twilio|telegram|discord",
    re.I,
)

IRREVERSIBLE = set(
    "delete del remove rm void drop destroy purge wipe truncate pay charge refund transfer wire payout "
    "send notify publish tweet deploy release merge approve reject sign submit cancel terminate revoke "
    "disable ban kick execute exec trigger invoke reserve purchase buy checkout".split()
)
WRITE = set(
    "create add record insert update upsert edit modify patch put set write save upload move rename copy "
    "assign invite share comment reply draft schedule tag label link attach enable close open archive star "
    "mark append import sync push commit".split()
)
READ = set(
    "get list read fetch search find lookup query retrieve view show describe browse count check status "
    "info inspect preview download export summarize summarise analyze analyse stats history".split()
)
CODE = {"bash", "shell", "execute_code", "code_interpreter", "python", "repl", "terminal", "run", "exec", "sandbox"}

# Known tool names across frameworks (Claude Code, LibreChat, LangChain, CrewAI, Copilot).
KNOWN = {
    # Claude Code / Copilot built-ins
    "read": "read", "glob": "read", "grep": "read", "ls": "read", "websearch": "read", "webfetch": "read",
    "todowrite": "write", "notebookedit": "write", "edit": "write", "write": "write", "multiedit": "write",
    "bash": "code", "task": "code", "agent": "code", "computer": "code", "execute": "code",
    # LibreChat
    "web_search": "read", "file_search": "read", "retrieval": "read", "memory": "write",
    "execute_code": "code", "code_interpreter": "code", "dalle": "write", "image_gen_oai": "write",
    # CrewAI / LangChain common
    "serperdevtool": "read", "scrapewebsitetool": "read", "websitesearchtool": "read", "filereadtool": "read",
    "directoryreadtool": "read", "pdfsearchtool": "read", "csvsearchtool": "read", "txtsearchtool": "read",
    "filewritertool": "write", "codeinterpretertool": "code", "codedocssearchtool": "read",
    "duckduckgosearchrun": "read", "tavilysearchresults": "read", "pythonrepltool": "code",
    "shelltool": "code", "terminal": "code", "requestsgettool": "read", "requestspostTool": "write",
    "gmailsendmessage": "irreversible", "gmailcreatedraft": "write", "sqldatabase": "write",
}

ACCESS_RANK = {"unknown": 0, "read": 1, "write": 2, "code": 3, "irreversible": 4}

# Charter Score weights, one per pillar. The single source for the census scan
# (score) and for charter files (census.charter.score_charter).
PILLAR_KEYS = ["owner", "recipient", "approval", "scope", "systems", "inputs", "escalation", "constraints"]
PILLAR_MAX = [20, 10, 15, 15, 10, 5, 15, 10]


def _tokens(name: str) -> list[str]:
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(name or ""))
    return [t for t in re.split(r"[^a-z0-9]+", s.lower()) if t]


def classify_tool(name: str) -> str:
    """Infer read / write / code / irreversible / unknown from a tool name."""
    low = str(name or "").strip().lower()
    if low in KNOWN:
        return KNOWN[low]
    toks = _tokens(name)
    for t in toks:
        if t in CODE:
            return "code"
    for t in toks:
        if t in IRREVERSIBLE:
            return "irreversible"
        if t in WRITE:
            return "write"
        if t in READ:
            return "read"
    return "unknown"


def access_mix(tools: list[str]) -> dict:
    mix = {"read": 0, "write": 0, "code": 0, "irreversible": 0, "unknown": 0}
    for t in tools:
        mix[classify_tool(t)] += 1
    return mix


def max_access(mix: dict) -> str:
    best = "none"
    rank = -1
    for k, n in mix.items():
        if n and ACCESS_RANK[k] > rank:
            best, rank = k, ACCESS_RANK[k]
    return best


def external_reach(tools: list[str], extra: bool = False) -> bool:
    return extra or any(EXTERNAL.search(str(t)) for t in tools)


# ------------------------------------------------------------- unit record
@dataclass
class AgentUnit:
    """One agent definition, already normalised by a parser."""
    source: str                 # github | npm | pypi | mcp_registry
    framework: str              # claude_code_subagent | copilot_agent | langgraph | crewai | ...
    kind: str                   # agent | mcp_server | mcp_client_config
    unit_ref: str               # stable identifier, hashed before storage
    instructions: str = ""
    tools: list[str] = field(default_factory=list)
    tools_all: bool = False     # inherits every tool (no tools field => all)
    external_extra: bool = False
    # structural facts supplied by the parser / collector
    owner_declared: bool = False        # owner / contact field, CODEOWNERS naming a person
    owner_on_record: bool = False       # repo owned by an individual account, maintainer listed
    owner_group_only: bool = False      # org or team only
    hold_structural: bool = False       # interrupt_before, human_input, ask permission, approval gate
    hold_kind: str = "none"             # explicit | platform_default | none
    deny_structural: bool = False       # explicit deny / disallowed tools list
    access_declared: bool = False       # tool list carries read/write/irreversible classes
    limits_structural: bool = False     # max iterations / rpm / spend / timeout / turns
    charter_json: bool = False
    charter_badge: bool = False
    # note: parsers may add free-form notes for debugging (not aggregated)
    notes: list[str] = field(default_factory=list)


def score(u: AgentUnit) -> dict:
    """Charter Score v0.1 (0-100) plus flags. Weights documented in README."""
    if u.hold_kind == "none" and u.hold_structural:
        u.hold_kind = "explicit"
    if u.hold_kind != "none":
        u.hold_structural = True
    text = u.instructions or ""
    chars = len(text)
    tools = list(u.tools)
    mix = access_mix(tools)
    top = max_access(mix)
    has_tools = bool(tools) or u.tools_all
    if u.tools_all and not tools:
        top = "code"  # inherits everything the host offers; treated as irreversible-like
    consequential = top in ("write", "code", "irreversible")
    ext = external_reach(tools, u.external_extra)

    escalate_txt = bool(ESCALATE.search(text))
    prohibit_txt = bool(PROHIBIT.search(text))
    scope_txt = bool(SCOPE.search(text))
    recipient_txt = bool(RECIPIENT.search(text)) or bool(EMAIL.search(text))
    inputs_txt = bool(INPUTS.search(text))
    irreversible_trigger_txt = bool(IRREVERSIBLE_TRIGGER.search(text))

    # Pillar 1 Owner (20)
    if u.owner_declared:
        p1 = 20
    elif u.owner_on_record:
        p1 = 8
    elif u.owner_group_only:
        p1 = 4
    else:
        p1 = 0
    # Pillar 2 Escalation recipient (10)
    p2 = 6 if recipient_txt else 0
    # Pillar 3 Approval authority (15): required when consequential
    p3 = 15 if (not consequential or u.hold_structural) else 0
    # Pillar 4 Scope never-do (15)
    p4 = 15 if u.deny_structural else (8 if prohibit_txt else 0)
    # Pillar 5 Systems (10)
    if not has_tools:
        p5 = 10
    elif u.access_declared:
        p5 = 10
    elif tools:
        p5 = 6
    else:
        p5 = 0  # inherits all tools: nothing is listed
    # Pillar 6 Inputs (5)
    p6 = 5 if (inputs_txt or not consequential) else 0
    # Pillar 7 Escalation rules (15)
    p7 = 15 if u.hold_structural else (8 if (escalate_txt or irreversible_trigger_txt) else 0)
    # Pillar 8 Constraints (10)
    irreversible_unheld = (top in ("irreversible", "code")) and not u.hold_structural
    if irreversible_unheld:
        p8 = 0
    elif u.limits_structural:
        p8 = 10
    else:
        p8 = 5
    total = p1 + p2 + p3 + p4 + p5 + p6 + p7 + p8

    capability_without_scope = has_tools and chars < 200
    outrun = consequential and not u.owner_declared and not u.hold_structural

    return {
        "source": u.source,
        "framework": u.framework,
        "kind": u.kind,
        "has_instructions": chars > 0,
        "instructions_chars": chars,
        "has_tools": has_tools,
        "tools_all": u.tools_all,
        "tools_count": len(tools),
        "access_read": mix["read"],
        "access_write": mix["write"],
        "access_code": mix["code"],
        "access_irreversible": mix["irreversible"],
        "access_unknown": mix["unknown"],
        "max_access": top,
        "consequential": consequential,
        "external_reach": ext,
        "owner_declared": u.owner_declared,
        "owner_on_record": u.owner_on_record,
        "owner_group_only": u.owner_group_only,
        "hold_structural": u.hold_structural,
        "hold_kind": u.hold_kind,
        "hold_explicit": u.hold_kind == "explicit",
        "deny_structural": u.deny_structural,
        "access_declared": u.access_declared,
        "limits_structural": u.limits_structural,
        "charter_json": u.charter_json,
        "charter_badge": u.charter_badge,
        "escalate_instructed": escalate_txt,
        "recipient_instructed": recipient_txt,
        "prohibit_instructed": prohibit_txt,
        "scope_instructed": scope_txt,
        "inputs_instructed": inputs_txt,
        "irreversible_trigger_instructed": irreversible_trigger_txt,
        "capability_without_scope": capability_without_scope,
        "irreversible_unheld": irreversible_unheld,
        "outrun": outrun,
        "pillars": [p1, p2, p3, p4, p5, p6, p7, p8],
        "charter_score": total,
    }


def unit_dict(u: AgentUnit) -> dict:
    return asdict(u)
