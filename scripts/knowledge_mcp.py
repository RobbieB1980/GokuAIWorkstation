#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from pathlib import Path

from mcp.server.fastmcp import FastMCP

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--db", required=True)
parser.add_argument("--root", required=True)
args, _unknown = parser.parse_known_args()

def _resolve_active_db(canonical: Path) -> Path:
    pointer = canonical.parent / "_ACTIVE_DB.txt"
    try:
        name = pointer.read_text(encoding="utf-8-sig").strip()
    except (FileNotFoundError, OSError):
        name = ""
    if name:
        candidate = (canonical.parent / name).resolve()
        try:
            candidate.relative_to(canonical.parent.resolve())
        except ValueError:
            return canonical
        if candidate.exists():
            return candidate
    return canonical

DB = _resolve_active_db(Path(args.db).resolve())
ROOT = Path(args.root).resolve()
mcp = FastMCP("minecraft-knowledge")
MAX_EVIDENCE_PACKET_CHARS = 9000
MAX_EXCERPT_CHARS = 4000
MAX_PRIMER_EXCERPTS = 12
MAX_SOURCE_EXCERPTS = 8
PHYSICAL_CONTEXT_LINES = 16


def connect() -> sqlite3.Connection:
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def safe_query(q: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9_.$:/#-]+", q)
    if not tokens:
        return '""'
    return " AND ".join(f'"{t.replace(chr(34), "")}"' for t in tokens[:12])


def version_key(version: str) -> tuple[int, ...] | None:
    """Return a numeric Minecraft/NeoForge version key; reject non-release labels."""
    value = (version or "").strip()
    if not re.fullmatch(r"\d+(?:\.\d+)*", value):
        return None
    return tuple(int(part) for part in value.split("."))


def _version_between(version: str, source_version: str, target_version: str) -> bool:
    key = version_key(version)
    source = version_key(source_version)
    target = version_key(target_version)
    return key is not None and source is not None and target is not None and source < key <= target


def _exact_source_root(loader: str, version: str) -> tuple[Path | None, dict]:
    loader_name = (loader or "").strip().lower()
    loader_dir = {"neoforge": "NeoForge", "minecraft": "Minecraft"}.get(loader_name)
    if not loader_dir or version_key(version) is None:
        return None, {"error": "loader must be neoforge or minecraft and version must be numeric"}
    root = (ROOT / "Exact_Version_Sources" / loader_dir / version).resolve()
    manifest_path = root / ".rb-source-version.json"
    if not manifest_path.is_file():
        return None, {
            "error": "EXACT_VERSION_SOURCE_NOT_MATERIALIZED",
            "loader": loader_name,
            "version": version,
            "expected_manifest": str(manifest_path),
        }
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        return None, {"error": "INVALID_EXACT_VERSION_SOURCE_MANIFEST", "detail": str(exc)}
    if str(manifest.get("version")) != version or str(manifest.get("loader", "")).lower() != loader_name:
        return None, {
            "error": "EXACT_VERSION_SOURCE_MISMATCH",
            "requested_version": version,
            "manifest_version": manifest.get("version"),
            "source_root": str(root),
        }
    manifest["source_root"] = str(root)
    manifest["physical_path"] = str(root)
    return root, manifest


def _query_terms(query: str) -> list[str]:
    stop = {"the", "and", "for", "from", "with", "into", "using", "entity", "registration", "migration"}
    terms: list[str] = []
    for token in re.findall(r"[A-Za-z_$][A-Za-z0-9_.$-]{2,}", query or ""):
        if token.lower() not in stop and token.lower() not in {x.lower() for x in terms}:
            terms.append(token)
    return terms[:12]


def _line_excerpt(path: Path, line_number: int, context_lines: int = PHYSICAL_CONTEXT_LINES) -> dict:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    start = max(1, line_number - max(0, context_lines))
    end = min(len(lines), line_number + max(0, context_lines))
    content = "\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1))
    return {"start_line": start, "end_line": end, "content": content[:MAX_EXCERPT_CHARS]}


def _score_grep_line(line: str, matched: list[str], path_stem: str, rel_lower: str, query_terms: list[str] | None = None) -> int:
    """Rank API declarations above comments, imports, and first-line javadoc hits."""
    score = 10 * len(matched)
    stripped = line.strip()
    if stripped.startswith(("//", "*", "/*", "*/", "#")):
        score -= 30
    if stripped.startswith(("import ", "package ")):
        score -= 25
    if "/src/main/" in "/" + rel_lower:
        score += 8
    if "test" in rel_lower:
        score -= 8
    if re.search(r"\b(class|interface|record|enum)\b", line):
        score += 8
    if re.search(r"\b(public|protected|private|static|final)\b", line):
        score += 12
    stem = path_stem.lower()
    specific = [term for term in matched if term.lower().split(".")[-1] != stem]
    if specific:
        score += 40 * len(specific)
    elif any(term.lower().split(".")[-1] != stem for term in (query_terms or matched)):
        score -= 15
    for term in matched:
        simple = term.split(".")[-1]
        if stem == simple.lower():
            score += 20
        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(simple)}(?![A-Za-z0-9_])", line):
            score += 15
        if re.search(rf"\b{re.escape(simple)}\s*\(", line):
            score += 25
    return score


def _grep_tree(source_root: Path, query: str, limit: int, context_lines: int = PHYSICAL_CONTEXT_LINES) -> list[dict]:
    terms = _query_terms(query)
    if not terms:
        return []
    allowed = {".java", ".kt", ".kts", ".gradle", ".json", ".toml", ".md"}
    skipped = {".git", ".gradle", "build", "out", "runs", "node_modules"}
    candidates: list[tuple[int, dict]] = []
    for path in source_root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in allowed or any(part in skipped for part in path.parts):
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        best: tuple[int, int, list[str]] | None = None
        rel = str(path.relative_to(source_root)).replace("\\", "/")
        low = rel.lower()
        for index, line in enumerate(lines, 1):
            matched = [term for term in terms if term.lower() in line.lower()]
            if not matched:
                continue
            score = _score_grep_line(line, matched, path.stem, low, terms)
            if best is None or score > best[0]:
                best = (score, index, matched)
        if best is None:
            continue
        score, index, matched = best
        excerpt = _line_excerpt(path, index, context_lines)
        evidence_hash = hashlib.sha1(f"{path}|{index}".encode("utf-8")).hexdigest()[:10]
        candidates.append((score, {
            "evidence_id": f"SRC-{evidence_hash}",
            "path": rel,
            "physical_path": str(path),
            "source_root": str(source_root),
            "matched_terms": matched,
            **excerpt,
        }))
    candidates.sort(key=lambda item: (-item[0], len(item[1]["path"]), item[1]["path"]))
    return [item[1] for item in candidates[:limit]]
def db_has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(row[1] == column for row in conn.execute(f"PRAGMA table_info({table})"))


@mcp.tool()
def knowledge_status() -> str:
    """Return local knowledge index counts, category coverage, and registered physical sources."""
    if not DB.exists():
        return json.dumps({"ready": False, "db": str(DB)})
    with connect() as c:
        files = c.execute("SELECT COUNT(*) n FROM files").fetchone()["n"]
        chunks = c.execute("SELECT COUNT(*) n FROM chunks").fetchone()["n"]
        cats = [dict(r) for r in c.execute(
            "SELECT category, COUNT(*) AS files FROM files GROUP BY category ORDER BY category"
        )]
        if db_has_column(c, "files", "source_id"):
            sources = [dict(r) for r in c.execute(
                """SELECT source_id, source_root, COUNT(*) AS files
                   FROM files GROUP BY source_id, source_root ORDER BY source_id"""
            )]
        else:
            sources = [{"source_id": "local", "source_root": str(ROOT), "files": files}]
    return json.dumps({
        "ready": True,
        "db": str(DB),
        "files": files,
        "chunks": chunks,
        "categories": cats,
        "sources": sources,
        "zero_copy_schema": True,
    }, indent=2)


@mcp.tool()
def list_knowledge_sources() -> str:
    """List indexed source roots and file counts, including external in-place sources."""
    if not DB.exists():
        return json.dumps([])
    with connect() as c:
        if not db_has_column(c, "files", "source_id"):
            return json.dumps([{"source_id": "local", "source_root": str(ROOT)}], indent=2)
        rows = [dict(r) for r in c.execute(
            """SELECT source_id, source_root, COUNT(*) AS files
               FROM files GROUP BY source_id, source_root ORDER BY source_id"""
        )]
    return json.dumps(rows, indent=2)


@mcp.tool()
def search_knowledge(query: str, category: str = "", version: str = "", limit: int = 8) -> str:
    """Search indexed knowledge. Results include the canonical physical path used by SQLite/MCP."""
    limit = max(1, min(int(limit), 20))
    match = safe_query(query)
    sql = """
        SELECT f.path, f.physical_path, f.source_id, f.source_root,
               f.category, f.version, ch.start_line, ch.end_line,
               snippet(chunks_fts, 0, '[', ']', ' ... ', 18) AS snippet,
               bm25(chunks_fts) AS rank
        FROM chunks_fts
        JOIN chunks ch ON ch.id = CAST(chunks_fts.chunk_id AS INTEGER)
        JOIN files f ON f.id = ch.file_id
        WHERE chunks_fts MATCH ?
    """
    params: list[object] = [match]
    if category:
        sql += " AND f.category = ?"
        params.append(category)
    if version:
        sql += " AND f.version = ?"
        params.append(version)
    sql += " ORDER BY CASE WHEN f.category LIKE 'ExactSource:%' THEN 0 ELSE 1 END, rank LIMIT ?"
    params.append(limit)
    try:
        with connect() as c:
            rows = [dict(r) for r in c.execute(sql, params)]
    except sqlite3.OperationalError as exc:
        return json.dumps({"error": "Knowledge FTS query failed", "detail": str(exc), "query": query}, indent=2)
    return json.dumps(rows, indent=2)


def _resolve_reference_rows(kind: str, version: str, limit: int = 8) -> list[dict]:
    kind = (kind or "").strip().lower()
    version = (version or "").strip()
    limit = max(1, min(int(limit), 20))
    rules = {
        "primer": "category='Upstream:neoforge_primers'",
        "minecraft_reference": "category='Minecraft_Java_Server_Client'",
        "mcpconfig": "category='Upstream:mcpconfig'",
        "gradle": "(category='Upstream:gradle' OR lower(path) LIKE '%gradle%')",
    }
    if kind not in rules:
        return []
    sql = f"""
        SELECT path,physical_path,source_id,source_root,category,version
        FROM files WHERE version=? AND {rules[kind]}
        ORDER BY CASE
          WHEN lower(path) LIKE '%/index.md' THEN 0
          WHEN lower(path) LIKE '%/_source.json' THEN 1
          WHEN lower(path) LIKE '%/version.json' THEN 2
          WHEN lower(path) LIKE '%config.json' THEN 3
          ELSE 10 END, length(path), path LIMIT ?
    """
    with connect() as c:
        return [dict(r) for r in c.execute(sql, (version, limit))]


@mcp.tool()
def resolve_reference(kind: str, version: str, limit: int = 8) -> str:
    """Resolve exact-version primer/Minecraft/MCPConfig/Gradle entrypoints without semantic search."""
    allowed = ["primer", "minecraft_reference", "mcpconfig", "gradle"]
    if (kind or "").strip().lower() not in allowed:
        return json.dumps({"error": "unsupported reference kind", "allowed": allowed, "results": []}, indent=2)
    return json.dumps({"kind": kind, "version": version, "results": _resolve_reference_rows(kind, version, limit)}, indent=2)

def _primer_chain_rows(source_version: str, target_version: str, limit: int = 64) -> list[dict]:
    if version_key(source_version) is None or version_key(target_version) is None:
        return []
    if version_key(source_version) >= version_key(target_version):
        return []
    with connect() as c:
        rows = [dict(row) for row in c.execute(
            """SELECT path,physical_path,source_id,source_root,category,version
               FROM files WHERE category='Upstream:neoforge_primers'"""
        )]
    selected = [row for row in rows if _version_between(str(row.get("version") or ""), source_version, target_version)]
    selected.sort(key=lambda row: version_key(str(row.get("version"))) or ())
    deduped: list[dict] = []
    seen: set[str] = set()
    for row in selected:
        version = str(row.get("version"))
        if version in seen:
            continue
        seen.add(version)
        deduped.append(row)
    return deduped[:max(1, min(int(limit), 128))]


@mcp.tool()
def resolve_primer_chain(source_version: str, target_version: str, limit: int = 64) -> str:
    """Resolve every indexed primer delta after source_version through target_version in numeric order."""
    source_key = version_key(source_version)
    target_key = version_key(target_version)
    if source_key is None or target_key is None or source_key >= target_key:
        return json.dumps({
            "error": "source_version and target_version must be numeric and source_version must be older",
            "source_version": source_version,
            "target_version": target_version,
            "results": [],
        }, indent=2)
    rows = _primer_chain_rows(source_version, target_version, limit)
    versions = [str(row.get("version")) for row in rows]
    target_present = target_version in versions
    return json.dumps({
        "source_version": source_version,
        "target_version": target_version,
        "selection_rule": "source_version < primer_version <= target_version",
        "versions": versions,
        "target_primer_present": target_present,
        "complete": target_present,
        "results": rows,
    }, indent=2)


def _primer_excerpts(rows: list[dict], query: str, limit: int) -> list[dict]:
    terms = _query_terms(query)
    excerpts: list[dict] = []
    if not terms:
        return excerpts
    for row in rows:
        path = Path(str(row.get("physical_path") or ""))
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for index, line in enumerate(lines, 1):
            matched = [term for term in terms if term.lower() in line.lower()]
            if not matched:
                continue
            evidence_hash = hashlib.sha1(f"{path}|{index}".encode("utf-8")).hexdigest()[:10]
            excerpts.append({
                "evidence_id": f"PRIMER-{row.get('version')}-{evidence_hash}",
                "version": row.get("version"),
                "path": row.get("path"),
                "physical_path": str(path),
                "source_root": row.get("source_root"),
                "matched_terms": matched,
                **_line_excerpt(path, index, 2),
            })
            break
        if len(excerpts) >= limit:
            break
    return excerpts


def _primer_changes_paths(source_version: str, target_version: str) -> tuple[Path | None, Path | None]:
    base = ROOT / "NeoForge_Primers" / target_version
    exact_index = base / f"primer_changes_{source_version}-to-{target_version}.md"
    exact_shards = base / f"primer_changes_{source_version}-to-{target_version}"
    if exact_index.is_file():
        return exact_index, exact_shards if exact_shards.is_dir() else None
    if not base.is_dir():
        return None, None
    # Prefer any ledger ending at target; newest mtime wins.
    candidates = sorted(base.glob(f"primer_changes_*-to-{target_version}.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        return None, None
    index = candidates[0]
    shards = index.with_suffix("")
    return index, shards if shards.is_dir() else None


def _primer_changes_excerpts(source_version: str, target_version: str, query: str, limit: int) -> list[dict]:
    """Search compact primer_changes shards before full upstream primer bodies."""
    terms = _query_terms(query)
    index_path, shard_dir = _primer_changes_paths(source_version, target_version)
    if index_path is None:
        return []
    search_files: list[Path] = []
    if shard_dir is not None:
        # Newest deltas first: 26.2, 26.1, then descending mid-chain.
        search_files.extend(sorted(shard_dir.glob("*.md"), key=lambda p: version_key(p.stem) or (0,), reverse=True))
    search_files.append(index_path)
    excerpts: list[dict] = []
    if not terms:
        excerpts.append({
            "evidence_id": "PRIMER-CHANGES-INDEX",
            "version": target_version,
            "path": str(index_path.relative_to(ROOT)).replace("\\", "/"),
            "physical_path": str(index_path),
            "source_root": str(ROOT),
            "matched_terms": [],
            "note": "primer_changes index available; provide a query to extract shard hits",
            "start_line": 1,
            "end_line": 1,
            "content": index_path.read_text(encoding="utf-8", errors="replace")[:800],
        })
        return excerpts
    for path in search_files:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for index, line in enumerate(lines, 1):
            matched = [term for term in terms if term.lower() in line.lower()]
            if not matched:
                continue
            evidence_hash = hashlib.sha1(f"{path}|{index}".encode("utf-8")).hexdigest()[:10]
            version = path.stem if path.parent == shard_dir else target_version
            excerpts.append({
                "evidence_id": f"PRIMER-CHANGES-{version}-{evidence_hash}",
                "version": version,
                "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                "physical_path": str(path),
                "source_root": str(ROOT),
                "matched_terms": matched,
                "source": "primer_changes",
                **_line_excerpt(path, index, 2),
            })
            break
        if len(excerpts) >= limit:
            break
    return excerpts


def _bounded_packet(packet: dict, list_keys: list[str], max_chars: int) -> str:
    budget = max(2000, min(int(max_chars), MAX_EVIDENCE_PACKET_CHARS))
    encoded = json.dumps(packet, indent=2, ensure_ascii=False)
    while len(encoded) > budget:
        changed = False
        for key in reversed(list_keys):
            values = packet.get(key)
            if isinstance(values, list) and values:
                values.pop()
                packet["truncated"] = True
                changed = True
                break
        if not changed:
            packet["error"] = "EVIDENCE_PACKET_BUDGET_EXCEEDED"
            encoded = json.dumps(packet, separators=(",", ":"), ensure_ascii=False)
            return encoded[:budget]
        encoded = json.dumps(packet, indent=2, ensure_ascii=False)
    packet["packet_chars"] = len(encoded)
    encoded = json.dumps(packet, indent=2, ensure_ascii=False)
    if len(encoded) > budget:
        packet.pop("packet_chars", None)
        encoded = json.dumps(packet, indent=2, ensure_ascii=False)
    return encoded


@mcp.tool()
def grep_physical_source(loader: str, version: str, query: str, limit: int = 8, context_lines: int = PHYSICAL_CONTEXT_LINES) -> str:
    """Grep a separately materialized exact-version physical source root; adjacent versions are rejected."""
    source_root, manifest = _exact_source_root(loader, version)
    if source_root is None:
        return json.dumps(manifest, indent=2)
    results = _grep_tree(source_root, query, max(1, min(int(limit), MAX_SOURCE_EXCERPTS)), max(0, min(int(context_lines), 20)))
    for result in results:
        result["loader"] = loader.lower()
        result["version"] = version
        result["commit"] = manifest.get("commit")
    packet = {
        "loader": loader.lower(),
        "version": version,
        "query": query,
        "source_verification": manifest,
        "results": results,
    }
    return _bounded_packet(packet, ["results"], MAX_EVIDENCE_PACKET_CHARS)


@mcp.tool()
def read_physical_source(physical_path: str, loader: str, version: str, start_line: int = 1, end_line: int = 120) -> str:
    """Read a bounded excerpt only when the physical file belongs to the requested exact-version source root."""
    source_root, manifest = _exact_source_root(loader, version)
    if source_root is None:
        return json.dumps(manifest, indent=2)
    path = Path(physical_path).resolve()
    try:
        path.relative_to(source_root)
    except ValueError:
        return json.dumps({
            "error": "ADJACENT_OR_UNREGISTERED_SOURCE_BLOCKED",
            "physical_path": str(path),
            "required_source_root": str(source_root),
            "version": version,
        }, indent=2)
    if not path.is_file():
        return json.dumps({"error": "SOURCE_FILE_NOT_FOUND", "physical_path": str(path)}, indent=2)
    start = max(1, int(start_line))
    end = max(start, min(int(end_line), start + 120))
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    content = "\n".join(f"{i}: {lines[i - 1]}" for i in range(start, min(end, len(lines)) + 1))
    return json.dumps({
        "loader": loader.lower(), "version": version, "commit": manifest.get("commit"),
        "physical_path": str(path), "source_root": str(source_root),
        "start_line": start, "end_line": min(end, len(lines)), "content": content[:MAX_EXCERPT_CHARS],
    }, indent=2, ensure_ascii=False)


@mcp.tool()
def build_migration_evidence(source_version: str, target_version: str, query: str, loader: str = "neoforge", max_chars: int = 9000) -> str:
    """Build a compressed cumulative primer ledger plus exact-target physical-source evidence."""
    chain = _primer_chain_rows(source_version, target_version, 128)
    versions = [str(row.get("version")) for row in chain]
    source_root, manifest = _exact_source_root(loader, target_version)
    index_path, shard_dir = _primer_changes_paths(source_version, target_version)
    compact_hits = _primer_changes_excerpts(source_version, target_version, query, MAX_PRIMER_EXCERPTS)
    # Fall back to full primer bodies only when compact ledger has no term hits.
    full_hits = [] if compact_hits and any(h.get("matched_terms") for h in compact_hits) else _primer_excerpts(chain, query, MAX_PRIMER_EXCERPTS)
    packet = {
        "schema": "rb-migration-evidence-v1",
        "source_version": source_version,
        "target_version": target_version,
        "loader": loader.lower(),
        "query": query,
        "primer_chain": versions,
        "primer_selection_rule": "source_version < primer_version <= target_version",
        "target_primer_present": target_version in versions,
        "primer_changes_index": str(index_path) if index_path else None,
        "primer_changes_shards": str(shard_dir) if shard_dir else None,
        "source_verification": manifest,
        "target_source_excerpts": [],
        "relevant_primer_deltas": compact_hits + full_hits,
        "primer_delta_source": "primer_changes" if compact_hits and any(h.get("matched_terms") for h in compact_hits) else ("primer_changes_index" if compact_hits else "full_primers"),
        "grounding_rule": "Prefer primer_changes shards over full primer index.md; exact-target physical source is required for target API claims.",
    }
    if source_root is None:
        packet["error"] = "TARGET_SOURCE_VERIFICATION_REQUIRED"
        packet["claim_status"] = "BLOCKED"
    else:
        source_hits = _grep_tree(source_root, query, MAX_SOURCE_EXCERPTS, PHYSICAL_CONTEXT_LINES)
        for hit in source_hits:
            hit.update({"loader": loader.lower(), "version": target_version, "commit": manifest.get("commit")})
        packet["target_source_excerpts"] = source_hits
        packet["claim_status"] = "SOURCE_VERIFIED" if source_hits else "INSUFFICIENT_TARGET_SOURCE_EVIDENCE"
    return _bounded_packet(packet, ["target_source_excerpts", "relevant_primer_deltas"], max_chars)

@mcp.tool()
def follow_reference_links(path: str, limit: int = 12) -> str:
    """Follow local relative Markdown links from an indexed exact-version reference, returning indexed targets only."""
    full, meta = resolve_indexed_path(path)
    if full is None or not full.is_file():
        return json.dumps({"error": "Path is not an available indexed knowledge file", "path": path}, indent=2)
    text = full.read_text(encoding="utf-8", errors="replace")
    targets = []
    for m in re.finditer(r'\[[^\]]+\]\(([^)]+)\)', text):
        target = m.group(1).strip().split('#', 1)[0].strip()
        if not target or '://' in target or target.startswith('#'):
            continue
        candidate = str((full.parent / target).resolve())
        if candidate not in targets:
            targets.append(candidate)
    out = []
    with connect() as c:
        for target in targets:
            row = c.execute(
                """SELECT path,physical_path,source_id,source_root,category,version
                   FROM files WHERE physical_path=? LIMIT 1""", (target,)
            ).fetchone()
            if row and (not meta.get("version") or row["version"] == meta.get("version")):
                out.append(dict(row))
            if len(out) >= max(1, min(int(limit), 30)):
                break
    return json.dumps({"source": meta, "results": out}, indent=2)


@mcp.tool()
def find_symbol(symbol: str, category: str = "", version: str = "", limit: int = 12) -> str:
    """Find a Java class, method, field, mapping name, Gradle key, or resource symbol."""
    return search_knowledge(symbol, category=category, version=version, limit=limit)


@mcp.tool()
def list_versions(category: str) -> str:
    """List indexed versions or top-level project folders for a knowledge category."""
    with connect() as c:
        rows = [r["version"] for r in c.execute(
            "SELECT DISTINCT version FROM files WHERE category=? AND version<>''",
            (category,),
        )]
    rows.sort(key=lambda value: (version_key(value) is None, version_key(value) or (), value))
    return json.dumps(rows)


def resolve_indexed_path(path_text: str) -> tuple[Path | None, dict[str, str]]:
    """Resolve only local-root files or physical paths already present in the SQLite index."""
    if DB.exists():
        with connect() as c:
            cols = {row[1] for row in c.execute("PRAGMA table_info(files)")}
            if "physical_path" in cols:
                row = c.execute(
                    """SELECT path,physical_path,source_id,source_root,category,version
                       FROM files WHERE path=? OR physical_path=? LIMIT 1""",
                    (path_text, path_text),
                ).fetchone()
                if row and row["physical_path"]:
                    return Path(row["physical_path"]), {
                        "path": row["path"],
                        "physical_path": row["physical_path"],
                        "source_id": row["source_id"] or "local",
                        "source_root": row["source_root"] or str(ROOT),
                        "category": row["category"] or "",
                        "version": row["version"] or "",
                    }

    # Backward-compatible local-root fallback. External arbitrary paths are never accepted.
    rel = Path(path_text)
    if rel.is_absolute():
        return None, {}
    full = (ROOT / rel).resolve()
    try:
        full.relative_to(ROOT)
    except ValueError:
        return None, {}
    return full, {
        "path": str(rel).replace("\\", "/"),
        "physical_path": str(full),
        "source_id": "local",
        "source_root": str(ROOT),
        "category": "",
        "version": "",
    }


@mcp.tool()
def read_reference(path: str, start_line: int = 1, end_line: int = 120) -> str:
    """Read a bounded line range from an indexed local or external physical file."""
    full, meta = resolve_indexed_path(path)
    if full is None:
        return json.dumps({"error": "Path is not an indexed knowledge file", "path": path})
    if not full.exists() or not full.is_file():
        return json.dumps({"error": "Indexed file is currently unavailable", **meta})
    start = max(1, int(start_line))
    end = max(start, min(int(end_line), start + 240))
    text = full.read_text(encoding="utf-8", errors="replace").splitlines()
    data = [{"line": i + 1, "text": text[i]} for i in range(start - 1, min(end, len(text)))]
    return json.dumps({**meta, "lines": data}, ensure_ascii=False)


@mcp.tool()
def search_solved_projects(query: str, limit: int = 8) -> str:
    """Search canonical completed GrokBuild projects, local solved-workspace/problem knowledge, and 262-repair remaps (category 262r)."""
    results = []
    for cat in ("Completed_Projects", "Gradle_Workspaces", "MCreator_Gradle_Builds", "Solved_Problems", "262r"):
        try:
            part = json.loads(search_knowledge(query, category=cat, limit=limit))
            results.extend(part)
        except Exception:
            pass
    return json.dumps(results[: max(1, min(limit, 20))], indent=2)


def mapping_db_path() -> Path:
    return _resolve_active_db(ROOT / "Minecraft_Mappings_Corpus" / "mappings.db")


@mcp.tool()
def mapping_status() -> str:
    """Return coverage of the compact incremental Minecraft mapping crosswalk index."""
    mdb = mapping_db_path()
    if not mdb.exists():
        return json.dumps({"ready": False, "db": str(mdb)})
    with sqlite3.connect(mdb) as c:
        versions = [r[0] for r in c.execute("SELECT DISTINCT minecraft_version FROM sources ORDER BY minecraft_version")]
        sources = c.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        symbols = c.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
        schema = c.execute("PRAGMA user_version").fetchone()[0]
    return json.dumps({"ready": True, "db": str(mdb), "schema": schema, "versions": versions,
                       "sources": sources, "symbols": symbols, "zero_copy": True,
                       "incremental": schema >= 2}, indent=2)


@mcp.tool()
def search_mappings(symbol: str, minecraft_version: str = "", namespace: str = "", limit: int = 20) -> str:
    """Search compact mapping edges in either direction across obfuscated/SRG/MCP/official names."""
    mdb = mapping_db_path()
    if not mdb.exists():
        return json.dumps({"error": "Mapping corpus has not been built", "db": str(mdb)})
    limit = max(1, min(int(limit), 50))
    token = f"%{symbol}%"
    sql = """SELECT sy.minecraft_version,sy.namespace_from,sy.namespace_to,sy.kind,sy.owner_from,sy.owner_to,
                    sy.name_from,sy.name_to,sy.signature,so.physical_path AS source_path
             FROM symbols sy JOIN sources so ON so.id=sy.source_id
             WHERE (sy.name_from LIKE ? OR sy.name_to LIKE ?)"""
    params: list[object] = [token, token]
    if minecraft_version:
        sql += " AND sy.minecraft_version=?"; params.append(minecraft_version)
    if namespace:
        sql += " AND (sy.namespace_from=? OR sy.namespace_to=?)"; params.extend([namespace, namespace])
    sql += " ORDER BY sy.minecraft_version,sy.kind,sy.name_from LIMIT ?"; params.append(limit)
    with sqlite3.connect(mdb) as c:
        c.row_factory = sqlite3.Row
        rows = [dict(r) for r in c.execute(sql, params)]
    return json.dumps(rows, indent=2)


def _mapping_neighbors(c: sqlite3.Connection, version: str, namespace: str, symbol: str) -> list[dict]:
    c.row_factory = sqlite3.Row
    rows = [dict(r) for r in c.execute("""
        SELECT sy.namespace_from,sy.namespace_to,sy.kind,sy.owner_from,sy.owner_to,
               sy.name_from,sy.name_to,sy.signature,so.physical_path AS source_path
        FROM symbols sy JOIN sources so ON so.id=sy.source_id
        WHERE sy.minecraft_version=? AND (
            (sy.namespace_from=? AND sy.name_from=?) OR
            (sy.namespace_to=? AND sy.name_to=?)
        )
    """, (version, namespace, symbol, namespace, symbol))]
    out = []
    for row in rows:
        if row['namespace_from'] == namespace and row['name_from'] == symbol:
            out.append({"next_namespace": row['namespace_to'], "next_symbol": row['name_to'], "edge": row, "direction": "forward"})
        if row['namespace_to'] == namespace and row['name_to'] == symbol:
            out.append({"next_namespace": row['namespace_from'], "next_symbol": row['name_from'], "edge": row, "direction": "reverse"})
    return out


@mcp.tool()
def resolve_mapping(symbol: str, minecraft_version: str, source_namespace: str, target_namespace: str, max_hops: int = 3) -> str:
    """Deterministically translate one symbol from an explicit source namespace to an explicit target namespace."""
    mdb = mapping_db_path()
    if not mdb.exists():
        return json.dumps({"error": "Mapping corpus has not been built", "db": str(mdb)})
    source_namespace = source_namespace.strip().lower()
    target_namespace = target_namespace.strip().lower()
    valid = {"obfuscated", "srg", "mcp", "official"}
    if source_namespace not in valid or target_namespace not in valid:
        return json.dumps({"error": "source_namespace and target_namespace must be one of obfuscated/srg/mcp/official"})
    if source_namespace == target_namespace:
        return json.dumps({"input": symbol, "version": minecraft_version,
                           "source_namespace": source_namespace, "target_namespace": target_namespace,
                           "result": symbol, "path": []}, indent=2)
    max_hops = max(1, min(int(max_hops), 4))
    with sqlite3.connect(mdb) as c:
        if not _mapping_neighbors(c, minecraft_version, source_namespace, symbol):
            return json.dumps({"input": symbol, "version": minecraft_version,
                               "source_namespace": source_namespace, "target_namespace": target_namespace,
                               "result": None, "error": "Input symbol not found in the declared source namespace"}, indent=2)
        queue = [(symbol, source_namespace, [], 0)]
        seen = {(symbol, source_namespace)}
        while queue:
            current, ns, path, hops = queue.pop(0)
            if hops >= max_hops:
                continue
            for nb in _mapping_neighbors(c, minecraft_version, ns, current):
                new_path = path + [{**nb['edge'], "direction": nb['direction']}]
                if nb['next_namespace'] == target_namespace:
                    return json.dumps({"input": symbol, "version": minecraft_version,
                                       "source_namespace": source_namespace, "target_namespace": target_namespace,
                                       "result": nb['next_symbol'], "path": new_path}, indent=2)
                key = (nb['next_symbol'], nb['next_namespace'])
                if key not in seen:
                    seen.add(key)
                    queue.append((nb['next_symbol'], nb['next_namespace'], new_path, hops + 1))
    return json.dumps({"input": symbol, "version": minecraft_version,
                       "source_namespace": source_namespace, "target_namespace": target_namespace,
                       "result": None, "error": "No translation path found"}, indent=2)


@mcp.tool()
def translate_mapping(symbol: str, minecraft_version: str, target_namespace: str = "official", max_hops: int = 3) -> str:
    """Translate across compact mapping edges; edges are traversable forward or reverse."""
    mdb = mapping_db_path()
    if not mdb.exists():
        return json.dumps({"error": "Mapping corpus has not been built", "db": str(mdb)})
    target_namespace = target_namespace.strip().lower()
    max_hops = max(1, min(int(max_hops), 4))
    namespaces = ('obfuscated', 'srg', 'mcp', 'official')
    with sqlite3.connect(mdb) as c:
        # Discover all namespaces in which the literal input exists.
        starts = []
        for ns in namespaces:
            if _mapping_neighbors(c, minecraft_version, ns, symbol):
                starts.append((symbol, ns, [], 0))
        if target_namespace in [ns for _, ns, _, _ in starts]:
            return json.dumps({"input": symbol, "version": minecraft_version,
                               "target_namespace": target_namespace, "result": symbol, "path": []}, indent=2)
        queue = list(starts); seen = {(sym, ns) for sym, ns, _, _ in starts}
        while queue:
            current, ns, path, hops = queue.pop(0)
            if hops >= max_hops:
                continue
            for nb in _mapping_neighbors(c, minecraft_version, ns, current):
                new_path = path + [{**nb['edge'], "direction": nb['direction']}]
                if nb['next_namespace'] == target_namespace:
                    return json.dumps({"input": symbol, "version": minecraft_version,
                                       "target_namespace": target_namespace,
                                       "result": nb['next_symbol'], "path": new_path}, indent=2)
                key = (nb['next_symbol'], nb['next_namespace'])
                if key not in seen:
                    seen.add(key); queue.append((nb['next_symbol'], nb['next_namespace'], new_path, hops + 1))
    return json.dumps({"input": symbol, "version": minecraft_version, "target_namespace": target_namespace,
                       "result": None, "error": "No translation path found"}, indent=2)


if __name__ == "__main__":
    mcp.run()
