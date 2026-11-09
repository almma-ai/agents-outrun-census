"""
The query manifest is the census instrument. It is versioned: a change to any
query, unit rule or threshold bumps MANIFEST_VERSION and is noted in CHANGELOG.
Every edition records the manifest version it ran under.
"""

MANIFEST_VERSION = "1.0"

# GitHub code-search sources. Each query returns at most 1,000 results, so the
# collector slices by file size (size:a..b) to walk past the cap. "unit" says
# how a file becomes agents.
GITHUB_SOURCES = [
    {
        "framework": "claude_code_subagent",
        "query": "path:.claude/agents extension:md",
        "parser": "claude_code_subagent",
        "repo_files": [".claude/settings.json"],
        "unit": "one .md file = one agent",
    },
    {
        "framework": "copilot_custom_agent",
        "query": "path:.github/agents extension:md",
        "parser": "copilot_custom_agent",
        "repo_files": [],
        "unit": "one .md file = one agent",
    },
    {
        "framework": "crewai",
        "query": "filename:crew.py crewai",
        "parser": "crewai_py",
        "repo_files": [],
        "unit": "one Agent(...) call = one agent",
    },
    {
        "framework": "crewai",
        "query": "filename:agents.yaml crewai",
        "parser": "crewai_yaml",
        "repo_files": [],
        "unit": "one top-level entry with role/goal/backstory = one agent",
    },
    {
        "framework": "langgraph",
        "query": "filename:langgraph.json",
        "parser": "langgraph",
        "repo_files": [],
        "follow_graph_modules": True,
        "unit": "one entry in graphs{} = one agent",
    },
    {
        "framework": "a2a_agent_card",
        "query": "filename:agent.json path:.well-known",
        "parser": "a2a_agent_card",
        "repo_files": [],
        "unit": "one card = one agent",
    },
    {
        "framework": "mcp_client_config",
        "query": "\"mcpServers\" filename:claude_desktop_config.json",
        "parser": "mcp_client_config",
        "repo_files": [],
        "unit": "one config = one capability bundle (not an agent)",
    },
    {
        "framework": "mcp_client_config",
        "query": "filename:.mcp.json mcpServers",
        "parser": "mcp_client_config",
        "repo_files": [],
        "unit": "one config = one capability bundle (not an agent)",
    },
    {
        "framework": "librechat_config",
        "query": "filename:librechat.yaml mcpServers",
        "parser": "mcp_client_config",
        "repo_files": [],
        "unit": "one deployment config = one capability bundle",
    },
]

REGISTRY_SOURCES = [
    {"source": "npm", "framework": "mcp_server", "query": "keywords:mcp mcp-server"},
    {"source": "pypi", "framework": "mcp_server", "name_contains": "mcp"},
    {"source": "mcp_registry", "framework": "mcp_server", "url": "https://registry.modelcontextprotocol.io/v0/servers"},
]

# Published counts from 1 to 4 are shown as "<5" (agent-governance-check v1.1 rule).
SUPPRESS_BELOW = 5

# Size slices (bytes) used to walk past the 1,000-result cap per query.
SIZE_SLICES = [(0, 400), (400, 800), (800, 1200), (1200, 1800), (1800, 2600), (2600, 4000),
               (4000, 6000), (6000, 9000), (9000, 14000), (14000, 25000), (25000, 60000), (60000, 400000)]
