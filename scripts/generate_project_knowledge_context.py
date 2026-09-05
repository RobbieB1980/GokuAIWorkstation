#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, sqlite3
from pathlib import Path


def active_db(canonical: Path) -> Path:
    pointer = canonical.parent / '_ACTIVE_DB.txt'
    try:
        name = pointer.read_text(encoding='utf-8-sig').strip()
    except OSError:
        name = ''
    if name:
        p = (canonical.parent / name).resolve()
        if p.exists():
            return p
    return canonical


def resolve_data_root(station_root: Path) -> Path:
    """Prefer GokuAI Data/, fall back to legacy knowledge/ layout."""
    data = station_root / 'Data'
    if data.is_dir():
        return data
    legacy = station_root / 'knowledge'
    if legacy.is_dir():
        return legacy
    return data


def resolve_knowledge_db(station_root: Path, data_root: Path) -> Path:
    candidates = [
        station_root / 'DataIndex' / 'minecraft-knowledge' / 'knowledge.db',
        data_root / 'Index' / 'knowledge.db',
        station_root / 'knowledge' / 'Index' / 'knowledge.db',
    ]
    for canonical in candidates:
        db = active_db(canonical)
        if db.exists():
            return db
    return active_db(candidates[0])


def resolve_mapping_db(data_root: Path, station_root: Path) -> Path:
    candidates = [
        data_root / 'Minecraft_Mappings_Corpus' / 'mappings.db',
        station_root / 'knowledge' / 'Minecraft_Mappings_Corpus' / 'mappings.db',
    ]
    for canonical in candidates:
        db = active_db(canonical)
        if db.exists():
            return db
    return active_db(candidates[0])


def resolve_ref(conn: sqlite3.Connection, kind: str, version: str):
    rules = {
        'primer': "category='Upstream:neoforge_primers'",
        'minecraft_reference': "category='Minecraft_Java_Server_Client'",
        'mcpconfig': "category='Upstream:mcpconfig'",
        'gradle': "(category='Upstream:gradle' OR lower(path) LIKE '%gradle%')",
    }
    sql = f"""
        SELECT path,physical_path,source_id,source_root,category,version
        FROM files WHERE version=? AND {rules[kind]}
        ORDER BY CASE
          WHEN lower(path) LIKE '%/index.md' THEN 0
          WHEN lower(path) LIKE '%/_source.json' THEN 1
          WHEN lower(path) LIKE '%/version.json' THEN 2
          WHEN lower(path) LIKE '%config.json' THEN 3
          ELSE 10 END, length(path), path LIMIT 1
    """
    row = conn.execute(sql, (version,)).fetchone()
    return dict(row) if row else None


def resolve_primer_changes(data_root: Path, source: str, target: str) -> dict | None:
    """Prefer compact primer_changes ledger over full upstream primer bodies."""
    index = data_root / 'NeoForge_Primers' / target / f'primer_changes_{source}-to-{target}.md'
    shard_dir = data_root / 'NeoForge_Primers' / target / f'primer_changes_{source}-to-{target}'
    if not index.is_file():
        base = data_root / 'NeoForge_Primers' / target
        candidates = []
        if base.is_dir():
            for path in base.glob(f'primer_changes_*-to-{target}.md'):
                name = path.stem
                prefix = 'primer_changes_'
                suffix = f'-to-{target}'
                if not (name.startswith(prefix) and name.endswith(suffix)):
                    continue
                src = name[len(prefix):-len(suffix)]
                def vkey(v: str):
                    try:
                        return [int(p) for p in v.split('.')]
                    except ValueError:
                        return None
                sk, declared = vkey(src), vkey(source)
                if sk is None or declared is None:
                    continue
                if sk <= declared:
                    candidates.append((sk, path))
        if not candidates:
            return None
        candidates.sort(key=lambda t: t[0], reverse=True)
        index = candidates[0][1]
        shard_dir = index.with_suffix('')
    try:
        rel = str(index.relative_to(data_root)).replace('\\', '/')
    except ValueError:
        rel = str(index)
    return {
        'index_path': str(index),
        'shard_dir': str(shard_dir) if shard_dir.is_dir() else '',
        'physical_path': str(index),
        'path': rel,
        'category': 'NeoForge_Primers',
        'version': target,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=r'C:\gokuai', help='GokuAI station root (or legacy RBLocalLLM root)')
    ap.add_argument('--data-root', default='', help='Override knowledge data root (default: <root>/Data)')
    ap.add_argument('--project', required=True)
    ns = ap.parse_args()

    station_root = Path(ns.root).resolve()
    data_root = Path(ns.data_root).resolve() if ns.data_root else resolve_data_root(station_root)
    project = Path(ns.project).resolve()
    manifest = project / '.rb-migration' / 'project.json'
    if not manifest.exists():
        raise SystemExit(f'Project manifest missing: {manifest}')
    meta = json.loads(manifest.read_text(encoding='utf-8-sig'))
    source = str(meta.get('source_version', '')).strip()
    target = str(meta.get('target_version', '')).strip()
    if not source or not target:
        raise SystemExit('project.json must declare source_version and target_version')

    db = resolve_knowledge_db(station_root, data_root)
    if not db.exists():
        raise SystemExit(f'Knowledge DB missing: {db}')
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    sources = [dict(r) for r in conn.execute(
        "SELECT source_id,source_root,COUNT(*) files FROM files GROUP BY source_id,source_root ORDER BY source_id,source_root"
    )]
    primer = resolve_ref(conn, 'primer', target)
    minecraft_reference = resolve_ref(conn, 'minecraft_reference', source)
    mcpconfig = resolve_ref(conn, 'mcpconfig', source)
    gradle = resolve_ref(conn, 'gradle', target)
    conn.close()
    primer_changes = resolve_primer_changes(data_root, source, target)

    mapping_db = resolve_mapping_db(data_root, station_root)
    mapping_ready = mapping_db.exists()

    rules_dir = project / '.grok' / 'rules'
    rules_dir.mkdir(parents=True, exist_ok=True)

    live = [
        '# Live Minecraft Knowledge Sources', '',
        f'- Declared source version: **{source}** (must be >= 1.20.1; detect exact artifact version)',
        f'- Declared target version: **{target}**',
        '- Conversion track: **modern detected-source → 26.2** (legacy 1.20.1 → 26.1 is frozen)', '',
        '## Hard rules', '',
        '- Workspace = the mod being migrated. Knowledge = the registered roots below.',
        '- Index locates. Source directories teach.',
        '- Detect the artifact exact Minecraft version. Do not hardcode every job to start at 1.20.1.',
        f'- Prefer compact `primer_changes` ledger/shards for `{source} → {target}` before opening full primer `index.md` bodies.',
        f'- Before API edits, resolve the primer chain `{source} → {target}` (ledger first) and build migration evidence so no intermediate delta is skipped.',
        f'- Target API claims must be supported by files indexed as exact target version **{target}**.',
        '- Do not grep the migration project for Forge/NeoForge API truth.',
        '- Never treat an empty FTS search as proof that a version or API is absent.',
        '- Never use an adjacent version as authoritative unless comparison is explicitly requested.',
        '- Mapping translation must use minecraft-knowledge resolve_mapping with explicit namespaces.',
        '- If the input jar/mod is older than 1.20.1, stop and report out-of-scope.',
        '- Indexer policy: **GokuAI only** (`C:\\gokuai\\Data`). Do not register external `H:\\` trees.', '',
        '## Registered source roots', '',
        'Policy: **GokuAI only** — index `C:\\gokuai\\Data` (`local`). External trees (e.g. `H:\\GrokBuild_MF\\Completed_Projects`) are not registered.', ''
    ]
    for s in sources:
        root = str(s.get('source_root') or '')
        if root and not root.lower().startswith(str(station_root).lower()):
            continue
        available = Path(s['source_root']).exists()
        live.append(f"- `{s['source_id']}` -> `{s['source_root']}` ({s['files']} indexed files; {'available' if available else 'currently unavailable'})")
    if not any(line.startswith('- `') for line in live[-8:]):
        live.append(f"- `local` -> `{data_root}` (GokuAI Data)")
    live += ['', '## Exact-version entrypoints', '']
    for label, obj in [
        ('Compact primer_changes ledger', primer_changes),
        ('Target primer (full, only if needed)', primer),
        ('Source Minecraft reference', minecraft_reference),
        ('Source MCPConfig', mcpconfig),
        ('Target Gradle reference', gradle),
    ]:
        live.append(f"- {label}: `{obj['physical_path']}`" if obj else f'- {label}: **not resolved**')
    if primer_changes and primer_changes.get('shard_dir'):
        live.append(f"- Primer_changes shards: `{primer_changes['shard_dir']}`")
    live.append(f"- 262-repair knowledge (category `262r`): `{data_root / '262r'}`")
    live += ['', f"- Mapping corpus: `{mapping_db}` ({'ready' if mapping_ready else 'not ready'})", '']
    (rules_dir / 'knowledge-sources.md').write_text('\n'.join(live), encoding='utf-8')

    solved = data_root / 'Solved_Problems' / 'legacy-java-converter-26.2'
    repair262 = data_root / '262r'
    session = [
        '# Session Knowledge Context', '',
        f'Source: **{source}**  ',
        f'Target: **{target}**',
        'Track: **modern only** (detected source ≥ 1.20.1 → 26.2). Legacy 1.20.1 → 26.1 is frozen.', '',
        '## Mandatory order BEFORE inventing any fix', '',
        '1. Read `SESSION-CONTINUE*.md` / project `AGENTS.md` handoff (current status).',
        '2. If repairing a converter output folder: read its `MIGRATION_EVIDENCE.md` + `SOURCE_PROFILE.json` + `compile-errors.log` first.',
        f'3. Open compact **primer_changes** index/shards for `{source}→{target}` (not every full primer).',
        f'4. Search 262-repair remaps under `{repair262}` (MCP category `262r`, version `26.2`) before inventing 26.2 compile/runtime remaps.',
        f'5. Search solved cases under `{solved}` (LEARNINGS, CASE-003/004/005, DFU/OVY/INT/PKG) before inventing remaps.',
        '6. Confirm APIs against exact NeoForge/Minecraft **26.2** physical source.',
        '7. Only then edit Java / encode converter rules.', '',
        f'Retrieval order: **detect source_version → open primer_changes index/shards for `{source}→{target}` → build_migration_evidence → exact-target physical source → cite that file**.',
        'Open **one primer_changes shard at a time**. Only open a full upstream primer `index.md` when a shard row needs surrounding prose.',
        'Never dump every full primer into local-worker context (32K/64K thrash).',
        'Do **not** invent a permanent client compile-gate when the primer Entity Render State path is unfinished.', ''
    ]
    if primer_changes:
        session.append(f"Compact primer_changes index: `{primer_changes['physical_path']}`")
        if primer_changes.get('shard_dir'):
            session.append(f"Primer_changes shards: `{primer_changes['shard_dir']}`")
    if primer:
        session.append(f"Full target primer (fallback only): `{primer['physical_path']}`")
    if minecraft_reference:
        session.append(f"Source Minecraft reference: `{minecraft_reference['physical_path']}`")
    if mcpconfig:
        session.append(f"Source MCPConfig: `{mcpconfig['physical_path']}`")
    session.append(f"262-repair knowledge: `{repair262}` (MCP category `262r`, version `26.2`)")
    session.append(f"Mapping corpus ready: **{'yes' if mapping_ready else 'no'}**")
    unavailable = [s for s in sources if not Path(s['source_root']).exists()]
    if unavailable:
        session += ['', 'Warning: registered knowledge source(s) currently offline:']
        session += [f"- `{s['source_id']}` -> `{s['source_root']}`" for s in unavailable]
    session += ['',
        'Hosted parent: resolve through MCP / primer_changes ledger, then grep/read the returned exact source_root/physical_path.',
        'Local workers: do not walk repositories; use the bounded evidence packet supplied by the parent.', ''
    ]
    (rules_dir / 'session-knowledge-context.md').write_text('\n'.join(session), encoding='utf-8')

    allow = [
        '# Knowledge Read Allowlist', '',
        'Knowledge/reference reads are allowed only from the migration project and GokuAI roots.',
        'Do not use this policy to block Gradle/JDK/build execution.', '',
        'Indexer policy: **GokuAI only** (`C:\\gokuai\\Data`). No external `H:\\` / Completed_Projects trees.', '',
        f'- `{project}`',
        f'- `{data_root}`',
        f'- `{station_root / "DataIndex"}`',
        f'- `{station_root / "tooling"}`',
    ]
    seen = {str(project).lower(), str(data_root).lower(), str(station_root / 'DataIndex').lower(), str(station_root / 'tooling').lower()}
    for s in sources:
        root = str(s.get('source_root') or '')
        if not root:
            continue
        # Enforce GokuAI-only allowlist even if a stale external source remains registered.
        if not root.lower().startswith(str(station_root).lower()):
            continue
        key = root.lower()
        if key in seen:
            continue
        seen.add(key)
        allow.append(f'- `{root}`')
    (rules_dir / 'knowledge-read-allowlist.md').write_text('\n'.join(allow) + '\n', encoding='utf-8')

    result = {
        'schema': 'goku-knowledge-wiring-v1',
        'project': str(project),
        'station_root': str(station_root),
        'data_root': str(data_root),
        'source_version': source,
        'target_version': target,
        'knowledge_db': str(db),
        'mapping_db': str(mapping_db),
        'mapping_ready': mapping_ready,
        'sources': sources,
        'primer_changes': primer_changes,
        'primer': primer,
        'minecraft_reference': minecraft_reference,
        'mcpconfig': mcpconfig,
        'gradle': gradle,
    }
    state = project / '.rb-migration' / 'knowledge-context.json'
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
