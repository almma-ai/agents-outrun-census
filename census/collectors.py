"""
Collectors fetch public agent definitions and yield (text, ctx) pairs or
metadata dicts. They are rate-limit aware and resumable; nothing here writes.

GitHub: code search (10 req/min authenticated, 1,000 results per query) plus
the Git blobs API (5,000-15,000 req/hour). Set GITHUB_TOKEN.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
from typing import Iterator

import requests

GH = "https://api.github.com"
UA = {"User-Agent": "agents-outrun-census/1.0 (+https://github.com/almma-ai)"}


class GitHub:
    def __init__(self, token: str | None = None, sleep_search: float = 6.5):
        self.s = requests.Session()
        self.s.headers.update(UA)
        self.s.headers["Accept"] = "application/vnd.github+json"
        token = token or os.environ.get("GITHUB_TOKEN")
        if token:
            self.s.headers["Authorization"] = f"Bearer {token}"
        self.sleep_search = sleep_search
        self.raw_s = requests.Session()          # no token: raw.githubusercontent.com is public
        self.raw_s.headers.update(UA)
        self._codeowners: dict[str, str | None] = {}
        self._repo_file: dict[tuple, str | None] = {}
        self.calls = 0

    # ---- low level
    def _get(self, url: str, **kw) -> requests.Response:
        for attempt in range(6):
            r = self.s.get(url, timeout=60, **kw)
            self.calls += 1
            if r.status_code in (403, 429) and ("rate limit" in r.text.lower() or r.headers.get("Retry-After")):
                reset = r.headers.get("X-RateLimit-Reset")
                wait = int(r.headers.get("Retry-After") or 0) or (max(5, int(reset) - int(time.time())) if reset else 60)
                time.sleep(min(wait, 120) + 1)
                continue
            if r.status_code >= 500:
                time.sleep(5 * (attempt + 1))
                continue
            return r
        return r

    def search_code(self, q: str, max_pages: int = 10) -> Iterator[dict]:
        page = 1
        while page <= max_pages:
            r = self._get(f"{GH}/search/code", params={"q": q, "per_page": 100, "page": page})
            if r.status_code != 200:
                break
            data = r.json()
            items = data.get("items") or []
            for it in items:
                yield it
            if len(items) < 100 or page * 100 >= min(data.get("total_count", 0), 1000):
                break
            page += 1
            time.sleep(self.sleep_search)
        time.sleep(self.sleep_search)

    def search_code_sliced(self, q: str, slices: list[tuple[int, int]], max_items: int) -> Iterator[dict]:
        """Walk past the 1,000 cap by slicing on file size."""
        n = 0
        per_slice = max(1, -(-max_items // len(slices)))   # spread the sample across sizes
        pages = max(1, -(-per_slice // 100))
        for lo, hi in slices:
            k = 0
            for it in self.search_code(f"{q} size:{lo}..{hi}", max_pages=pages):
                yield it
                n += 1
                k += 1
                if n >= max_items:
                    return
                if k >= per_slice:
                    break

    def raw(self, repo: str, path: str) -> str | None:
        """Public file content via raw.githubusercontent.com (HEAD = default branch).
        Falls back to the contents API when raw is unavailable."""
        for attempt in range(3):
            try:
                r = self.raw_s.get(f"https://raw.githubusercontent.com/{repo}/HEAD/{path}", timeout=60)
            except requests.RequestException:
                time.sleep(2)
                continue
            self.calls += 1
            if r.status_code == 200:
                time.sleep(0.15)
                return r.text
            if r.status_code == 404:
                return None
            if r.status_code in (429, 403):
                time.sleep(30 * (attempt + 1))
                continue
            break
        r = self._get(f"{GH}/repos/{repo}/contents/{path}")
        if r.status_code == 200:
            d = r.json()
            if isinstance(d, dict) and d.get("encoding") == "base64":
                return base64.b64decode(d["content"]).decode("utf-8", "replace")
        return None

    def blob(self, repo: str, sha: str, path: str = "") -> str | None:
        return self.raw(repo, path) if path else None

    def repo_file(self, repo: str, path: str) -> str | None:
        key = (repo, path)
        if key in self._repo_file:
            return self._repo_file[key]
        txt = self.raw(repo, path)
        self._repo_file[key] = txt
        return txt

    def codeowners(self, repo: str) -> str | None:
        """'person' if any individual @handle or email is an owner, 'group' if teams only, None if absent."""
        if repo in self._codeowners:
            return self._codeowners[repo]
        kind = None
        for p in (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS"):
            txt = self.repo_file(repo, p)
            if txt is None:
                continue
            handles = re.findall(r"(?<![\w/])@([\w-]+)(/[\w-]+)?", txt)
            emails = re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", txt)
            if emails or any(team == "" for _, team in handles):
                kind = "person"
            elif handles:
                kind = "group"
            else:
                kind = "group"
            break
        self._codeowners[repo] = kind
        return kind


def github_source(gh: GitHub, src: dict, max_items: int, slices, keep_ids: bool,
                  per_repo_cap: int = 0) -> Iterator[tuple[str, dict]]:
    seen = set()
    per_repo: dict[str, int] = {}
    for it in gh.search_code_sliced(src["query"], slices, max_items):
        repo = it["repository"]["full_name"]
        path = it["path"]
        key = (repo, path)
        if key in seen:
            continue
        seen.add(key)
        if per_repo_cap and per_repo.get(repo, 0) >= per_repo_cap:
            continue
        per_repo[repo] = per_repo.get(repo, 0) + 1
        text = gh.blob(repo, it["sha"], path)
        if text is None:
            continue
        ctx = {
            "repo": repo,
            "path": path,
            "owner_type": (it["repository"].get("owner") or {}).get("type"),
            "codeowners": gh.codeowners(repo),
            "framework_hint": src["framework"] if src["parser"] == "mcp_client_config" else None,
        }
        for rf in src.get("repo_files", []):
            txt = gh.repo_file(repo, rf)
            if txt and rf.endswith("settings.json"):
                try:
                    perms = (json.loads(txt).get("permissions") or {})
                    ctx["settings_deny"] = bool(perms.get("deny"))
                    ctx["settings_allow"] = bool(perms.get("allow"))
                    # pre-approved consequential tools remove the platform-default hold
                    ctx["preapproved_consequential"] = any(
                        re.match(r"(Bash|Edit|Write|MultiEdit|NotebookEdit)\b", str(x)) for x in (perms.get("allow") or []))
                    ctx["bypass_mode"] = str(perms.get("defaultMode") or "") in ("bypassPermissions", "acceptEdits", "dontAsk")
                except Exception:
                    pass
        if src.get("follow_graph_modules"):
            extra = {}
            try:
                graphs = (json.loads(text).get("graphs") or {})
                base = path.rsplit("/", 1)[0] + "/" if "/" in path else ""
                for target in list(graphs.values())[:40]:
                    if not isinstance(target, str):
                        continue
                    mod = re.sub(r"^\./", "", target.split(":")[0])
                    cands = []
                    if re.search(r"\.(py|ts|js|mjs|tsx)$", mod):
                        cands = [base + mod, mod, base + "src/" + mod]
                    else:  # python module notation: pkg.sub.graph
                        fp = mod.replace(".", "/") + ".py"
                        cands = [base + fp, base + "src/" + fp, fp, "src/" + fp]
                    txt = None
                    for c in cands:
                        txt = gh.repo_file(repo, c)
                        if txt:
                            break
                    if txt:
                        extra[mod] = txt
            except Exception:
                pass
            ctx["extra_files"] = extra
        yield text, ctx


# ----------------------------------------------------------------- registries
def npm_mcp_servers(max_items: int = 1000) -> Iterator[dict]:
    s = requests.Session()
    s.headers.update(UA)
    got = 0
    offset = 0
    while got < max_items:
        r = s.get("https://registry.npmjs.org/-/v1/search",
                  params={"text": "keywords:mcp mcp server", "size": 250, "from": offset}, timeout=60)
        if r.status_code != 200:
            break
        objs = r.json().get("objects") or []
        if not objs:
            break
        for o in objs:
            p = o.get("package") or {}
            yield {
                "name": p.get("name"), "description": p.get("description"),
                "author": p.get("author") or p.get("publisher"),
                "maintainers": p.get("maintainers") or [],
                "keywords": p.get("keywords") or [],
            }
            got += 1
            if got >= max_items:
                break
        offset += len(objs)
        time.sleep(0.5)


def pypi_mcp_servers(max_items: int = 1000, name_contains: str = "mcp") -> Iterator[dict]:
    s = requests.Session()
    s.headers.update(UA)
    r = s.get("https://pypi.org/simple/", headers={"Accept": "application/vnd.pypi.simple.v1+json"}, timeout=120)
    if r.status_code != 200:
        return
    names = [p["name"] for p in r.json().get("projects", []) if name_contains in p["name"].lower()]
    names = [n for n in names if re.search(r"mcp[-_]?server|server[-_]?mcp|^mcp[-_]", n.lower())]
    for n in names[:max_items]:
        rr = s.get(f"https://pypi.org/pypi/{n}/json", timeout=60)
        if rr.status_code != 200:
            continue
        info = rr.json().get("info") or {}
        author = info.get("author") or info.get("author_email") or info.get("maintainer") or info.get("maintainer_email")
        yield {
            "name": info.get("name"), "description": info.get("summary"),
            "author": author, "maintainers": [], "keywords": (info.get("keywords") or "").split(","),
        }
        time.sleep(0.2)


def mcp_registry_servers(url: str, max_items: int = 5000) -> Iterator[dict]:
    s = requests.Session()
    s.headers.update(UA)
    cursor = None
    got = 0
    while got < max_items:
        params = {"limit": 100}
        if cursor:
            params["cursor"] = cursor
        r = s.get(url, params=params, timeout=60)
        if r.status_code != 200:
            break
        d = r.json()
        for entry in d.get("servers") or []:
            sv = entry.get("server") or entry
            yield {
                "name": sv.get("name"), "description": sv.get("description"),
                "author": None, "maintainers": [],
                "org_only": True,  # registry names are namespaced (io.github.org/...), no person field
                "repository": (sv.get("repository") or {}).get("url"),
            }
            got += 1
        cursor = (d.get("metadata") or {}).get("nextCursor")
        if not cursor:
            break
        time.sleep(0.3)
