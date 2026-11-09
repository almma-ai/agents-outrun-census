"""
Parsers: turn one fetched file (plus repository context) into AgentUnit(s).

Every parser is a pure function  parse_<framework>(text, ctx) -> list[AgentUnit].
ctx keys (all optional):
  repo            owner/name            (never stored unless --keep-ids)
  path            file path in repo
  owner_type      "User" | "Organization"
  codeowners      "person" | "group" | None   (from CODEOWNERS)
  settings_deny   bool  (.claude/settings.json has permissions.deny)
  settings_allow  bool  (.claude/settings.json has permissions.allow)
  extra_files     {path: text} fetched alongside (e.g. langgraph graph module)
"""
from __future__ import annotations

import json
import re
from typing import Callable

import yaml

from .signals import AgentUnit

LIMIT_WORDS = re.compile(
    r"max_iter|max_rpm|max_execution_time|max_retry|recursion_limit|maxTurns|max_turns|budget|"
    r"timeout|rate_limit|max_tokens_per_run|spend", re.I)


def _owner_flags(ctx: dict, declared_in_file: bool = False) -> dict:
    co = ctx.get("codeowners")
    owner_type = ctx.get("owner_type")
    return {
        "owner_declared": bool(declared_in_file or co == "person"),
        "owner_on_record": bool(owner_type == "User") and not declared_in_file and co != "person",
        "owner_group_only": bool(owner_type == "Organization" and co in (None, "group")) and not declared_in_file and co != "person",
    }


def _frontmatter(text: str) -> tuple[dict, str]:
    m = re.match(r"^﻿?---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if not m:
        return {}, text
    try:
        fm = yaml.safe_load(m.group(1)) or {}
        if not isinstance(fm, dict):
            fm = {}
    except Exception:
        fm = {}
    return fm, m.group(2)


def _as_list(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [t.strip() for t in re.split(r"[,\n]", v) if t.strip()]
    if isinstance(v, list):
        out = []
        for x in v:
            if isinstance(x, str):
                out.append(x.strip())
            elif isinstance(x, dict):
                out.extend(str(k) for k in x.keys())
        return out
    if isinstance(v, dict):
        return [str(k) for k in v.keys()]
    return [str(v)]


# ------------------------------------------------------------ Claude Code
def parse_claude_code_subagent(text: str, ctx: dict) -> list[AgentUnit]:
    fm, body = _frontmatter(text)
    tools = _as_list(fm.get("tools"))
    disallowed = _as_list(fm.get("disallowedTools") or fm.get("disallowed_tools"))
    mode = str(fm.get("permissionMode") or fm.get("permission_mode") or "").strip()
    bypass = (mode in ("bypassPermissions", "acceptEdits", "dontAsk", "auto")
              or bool(ctx.get("preapproved_consequential")) or bool(ctx.get("bypass_mode")))
    declared = any(k in fm for k in ("owner", "maintainer", "contact", "accountable"))
    u = AgentUnit(
        source="github", framework="claude_code_subagent", kind="agent",
        unit_ref=f"{ctx.get('repo')}:{ctx.get('path')}",
        instructions=(str(fm.get("description") or "") + "\n" + body).strip(),
        tools=tools, tools_all=not tools,
        hold_kind=("explicit" if mode == "plan" else ("none" if bypass else "platform_default")),
        deny_structural=bool(disallowed) or bool(ctx.get("settings_deny")),
        limits_structural=bool(fm.get("maxTurns") or fm.get("max_turns")),
        **_owner_flags(ctx, declared),
    )
    return [u]


# ---------------------------------------------------------- GitHub Copilot
def parse_copilot_agent(text: str, ctx: dict) -> list[AgentUnit]:
    fm, body = _frontmatter(text)
    tools = _as_list(fm.get("tools"))
    declared = any(k in fm for k in ("owner", "maintainer", "contact"))
    u = AgentUnit(
        source="github", framework="copilot_custom_agent", kind="agent",
        unit_ref=f"{ctx.get('repo')}:{ctx.get('path')}",
        instructions=(str(fm.get("description") or "") + "\n" + body).strip(),
        tools=tools, tools_all=not tools,
        hold_kind="platform_default",                # output is a pull request a person must merge
        deny_structural=False,
        **_owner_flags(ctx, declared),
    )
    return [u]


# ---------------------------------------------------------------- CrewAI
_AGENT_CALL = re.compile(r"Agent\s*\((.*?)\n\s*\)", re.S)
_KW_STR = lambda k: re.compile(k + r"\s*=\s*(?:f?[\"']{1,3})(.*?)(?:[\"']{1,3})", re.S)
_TOOLS_KW = re.compile(r"tools\s*=\s*\[(.*?)\]", re.S)
_TOOL_NAME = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(")


def parse_crewai_py(text: str, ctx: dict) -> list[AgentUnit]:
    units = []
    human_input = bool(re.search(r"human_input\s*=\s*True", text))
    limits = bool(re.search(r"max_iter|max_rpm|max_execution_time|max_retry_limit", text))
    for i, m in enumerate(_AGENT_CALL.finditer(text)):
        block = m.group(1)

        def kw(k: str) -> str:
            mm = _KW_STR(k).search(block)
            return mm.group(1) if mm else ""

        role, goal, back = kw("role"), kw("goal"), kw("backstory")
        tools = []
        tm = _TOOLS_KW.search(block)
        if tm:
            tools = [t for t in _TOOL_NAME.findall(tm.group(1))] or [t.strip() for t in tm.group(1).split(",") if t.strip()]
        units.append(AgentUnit(
            source="github", framework="crewai", kind="agent",
            unit_ref=f"{ctx.get('repo')}:{ctx.get('path')}#{i}",
            instructions="\n".join(x for x in (role, goal, back) if x),
            tools=tools, hold_structural=human_input, limits_structural=limits,
            **_owner_flags(ctx),
        ))
    return units


def parse_crewai_yaml(text: str, ctx: dict) -> list[AgentUnit]:
    try:
        data = yaml.safe_load(text)
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    units = []
    for name, spec in data.items():
        if not isinstance(spec, dict) or not any(k in spec for k in ("role", "goal", "backstory")):
            continue
        tools = _as_list(spec.get("tools"))
        units.append(AgentUnit(
            source="github", framework="crewai", kind="agent",
            unit_ref=f"{ctx.get('repo')}:{ctx.get('path')}#{name}",
            instructions="\n".join(str(spec.get(k) or "") for k in ("role", "goal", "backstory")).strip(),
            tools=tools,
            hold_structural=bool(spec.get("human_input")),
            limits_structural=any(k in spec for k in ("max_iter", "max_rpm", "max_execution_time")),
            **_owner_flags(ctx),
        ))
    return units


# -------------------------------------------------------------- LangGraph
_PY_STR = re.compile(r"(?:\"\"\"|''')(.*?)(?:\"\"\"|''')", re.S)
_TOOL_DEF = re.compile(r"@tool[^\n]*\n\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)")
_TS_TOOL = re.compile(r"(?:const|let)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:new\s+DynamicStructuredTool|tool)\s*\(")
_TS_STR = re.compile(r"`([^`]{80,})`", re.S)
_TOOLS_LIST = re.compile(r"tools\s*[:=]\s*\[(.*?)\]", re.S)


def parse_langgraph_json(text: str, ctx: dict) -> list[AgentUnit]:
    try:
        cfg = json.loads(text)
    except Exception:
        return []
    graphs = cfg.get("graphs") if isinstance(cfg, dict) else None
    if not isinstance(graphs, dict) or not graphs:
        return []
    extra = ctx.get("extra_files") or {}
    units = []
    for gname, target in graphs.items():
        mod_path = re.sub(r"^\./", "", str(target).split(":")[0]) if isinstance(target, str) else ""
        src = extra.get(mod_path, "")
        if not src:
            for p, t in extra.items():
                if p.endswith(mod_path) or mod_path.endswith(p):
                    src = t
                    break
        tools: list[str] = []
        instr = ""
        hold = False
        limits = False
        if src:
            tools = _TOOL_DEF.findall(src) + _TS_TOOL.findall(src)
            tm = _TOOLS_LIST.search(src)
            if tm:
                tools += [t.strip().split("(")[0] for t in tm.group(1).split(",") if t.strip() and not t.strip().startswith("//")]
            if re.search(r"bind_tools|bindTools|ToolNode|create_react_agent|createReactAgent", src) and not tools:
                tools = ["<tools_bound>"]
            # longest docstring / template string as the prompt
            strs = _PY_STR.findall(src) + _TS_STR.findall(src)
            if strs:
                instr = max(strs, key=len)
            hold = bool(re.search(r"interrupt_before|interrupt_after|interruptBefore|interruptAfter|\binterrupt\s*\(|HumanInTheLoop|human_in_the_loop|HumanInterrupt|add_human_in_the_loop", src))
            limits = bool(re.search(r"recursion_limit|recursionLimit|max_steps|timeout", src))
        units.append(AgentUnit(
            source="github", framework="langgraph", kind="agent",
            unit_ref=f"{ctx.get('repo')}:{ctx.get('path')}#{gname}",
            instructions=instr, tools=[t for t in tools if t],
            hold_structural=hold, limits_structural=limits,
            **_owner_flags(ctx),
        ))
        if not src:
            units[-1].notes.append("graph_module_not_fetched")
    return units


# ------------------------------------------------------------ A2A card
def parse_a2a_card(text: str, ctx: dict) -> list[AgentUnit]:
    try:
        card = json.loads(text)
    except Exception:
        return []
    if not isinstance(card, dict) or not ("skills" in card or "capabilities" in card):
        return []
    skills = card.get("skills") or []
    tools = [str(s.get("name") or s.get("id")) for s in skills if isinstance(s, dict)]
    desc = str(card.get("description") or "")
    for s in skills:
        if isinstance(s, dict):
            desc += "\n" + str(s.get("description") or "")
    provider = card.get("provider") or {}
    contact = bool(re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", json.dumps(provider)))
    u = AgentUnit(
        source="github", framework="a2a_agent_card", kind="agent",
        unit_ref=f"{ctx.get('repo')}:{ctx.get('path')}",
        instructions=desc.strip(), tools=tools, external_extra=bool(card.get("url")),
        **_owner_flags(ctx, declared_in_file=contact),
    )
    if provider and not contact:
        u.owner_group_only = True
        u.owner_on_record = False
    return [u]


# ------------------------------------------------- MCP client configurations
def parse_mcp_client_config(text: str, ctx: dict) -> list[AgentUnit]:
    """claude_desktop_config.json, .mcp.json, .cursor/mcp.json, librechat.yaml"""
    data = None
    try:
        data = json.loads(text)
    except Exception:
        try:
            data = yaml.safe_load(text)
        except Exception:
            return []
    if not isinstance(data, dict):
        return []
    servers = data.get("mcpServers") or data.get("mcp_servers") or {}
    if not isinstance(servers, dict) or not servers:
        return []
    names = list(servers.keys())
    hold = False
    deny = False
    ep = (data.get("endpoints") or {}).get("agents") if isinstance(data.get("endpoints"), dict) else None
    if isinstance(ep, dict) and ep.get("toolApproval"):
        hold = True
        deny = bool((ep.get("toolApproval") or {}).get("deny"))
    u = AgentUnit(
        source="github", framework=ctx.get("framework_hint") or "mcp_client_config", kind="mcp_client_config",
        unit_ref=f"{ctx.get('repo')}:{ctx.get('path')}",
        instructions="", tools=names, external_extra=True,
        hold_structural=hold, deny_structural=deny,
        **_owner_flags(ctx),
    )
    return [u]


# ------------------------------------------------------ MCP server metadata
def parse_mcp_server_meta(meta: dict, source: str) -> list[AgentUnit]:
    """npm / PyPI / registry metadata for one MCP server package."""
    name = str(meta.get("name") or "")
    desc = str(meta.get("description") or "")
    author = meta.get("author")
    maintainers = meta.get("maintainers") or []
    declared = False
    on_record = False
    if isinstance(author, dict) and (author.get("email") or author.get("name")):
        declared = True
    elif isinstance(author, str) and author.strip():
        declared = True
    elif maintainers:
        on_record = True
    tools = meta.get("tools") or []
    u = AgentUnit(
        source=source, framework="mcp_server", kind="mcp_server",
        unit_ref=f"{source}:{name}",
        instructions=desc, tools=[str(t) for t in tools] or [name],
        external_extra=True,
        owner_declared=declared, owner_on_record=on_record,
        owner_group_only=bool(meta.get("org_only")) and not declared and not on_record,
    )
    return [u]


PARSERS: dict[str, Callable[[str, dict], list[AgentUnit]]] = {
    "claude_code_subagent": parse_claude_code_subagent,
    "copilot_custom_agent": parse_copilot_agent,
    "crewai_py": parse_crewai_py,
    "crewai_yaml": parse_crewai_yaml,
    "langgraph": parse_langgraph_json,
    "a2a_agent_card": parse_a2a_card,
    "mcp_client_config": parse_mcp_client_config,
}
