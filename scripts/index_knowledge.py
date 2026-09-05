#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

SCHEMA_VERSION = 5
TEXT_EXTENSIONS = {
    '.md', '.txt', '.json', '.toml', '.gradle', '.properties', '.java', '.kt', '.kts',
    '.py', '.ps1', '.xml', '.yml', '.yaml', '.cfg', '.csv', '.tsrg', '.tiny', '.mapping',
    '.mappings', '.at', '.accesswidener', '.mcmeta', '.json5', '.js', '.ts', '.rs', '.groovy'
}
SPECIAL_NAMES = {'build.gradle', 'settings.gradle', 'gradle.properties', 'gradlew', 'gradlew.bat'}
SKIP_DIRS = {'.git', '.gradle', '.idea', '.venv', '__pycache__', 'node_modules', 'build', 'out', 'target'}
MAX_FILE_SIZE = 8 * 1024 * 1024
CHUNK_LINES = 90
CHUNK_CHARS = 14000


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    root: Path
    category: str | None = None
    external: bool = False


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def classify_local(root: Path, path: Path) -> tuple[str, str]:
    rel = path.relative_to(root)
    parts = rel.parts
    category = parts[0] if parts else 'Unknown'
    version = ''
    if category == 'Exact_Version_Sources' and len(parts) > 2:
        loader = parts[1].strip().lower()
        version = parts[2]
        category = f'ExactSource:{loader}' if loader else 'ExactSource'
        return category, version
    if category == '_upstream' and len(parts) > 1:
        repo = parts[1]
        category = f'Upstream:{repo}'
        if repo == 'neoforge_primers' and len(parts) > 3 and parts[2] == 'primers':
            version = parts[3]
        elif repo == 'mcpconfig' and len(parts) > 4 and parts[2:4] == ('versions', 'release'):
            version = parts[4]
    elif category in {'NeoForge_Primers', 'Minecraft_MCP_Mappings', 'Minecraft_Java_Server_Client'} and len(parts) > 1:
        version = parts[1]
    elif category in {'Gradle_Workspaces', 'Gradle_Builds', 'MCreator_Gradle_Builds'} and len(parts) > 1:
        version = parts[1]
    elif category == '262r':
        version = '26.2'
    return category, version


VERSION_SEGMENT_RE = re.compile(r"^(?:1\.\d{1,2}(?:\.\d{1,2})?|2[0-9]\.\d+(?:\.\d+)?)$")

def infer_exact_version(parts: tuple[str, ...]) -> str:
    """Return an exact Minecraft/NeoForge-style version found in path segments.

    Never infer from arbitrary prose or filenames; only directory-like path segments
    are accepted so Java/26.2/... becomes 26.2 while unrelated numbers are ignored.
    """
    for part in parts:
        clean = part.strip().strip('vV')
        if VERSION_SEGMENT_RE.fullmatch(clean):
            return clean
    return ''

def classify_source(source: SourceSpec, path: Path) -> tuple[str, str]:
    rel = path.relative_to(source.root)
    if source.category:
        # External sources (notably H:\GrokBuild_MF\Completed_Projects) used to
        # store rel.parts[0] (usually 'Java') as the version.  Use the first exact
        # version directory instead, e.g. Java/26.2/... -> 26.2.
        return source.category, infer_exact_version(rel.parts)
    category, version = classify_local(source.root, path)
    if not version:
        version = infer_exact_version(rel.parts)
    return category, version


def is_dedicated_mapping_source(source: SourceSpec, p: Path) -> bool:
    """Mapping text belongs in mappings.db, not duplicated into the general FTS index."""
    suffix = p.suffix.lower()
    name = p.name.lower()
    if suffix in {'.tsrg', '.tiny', '.mapping', '.mappings'}:
        return True
    try:
        rel_parts = p.relative_to(source.root).parts
    except ValueError:
        rel_parts = ()
    if not source.external and rel_parts:
        top = rel_parts[0]
        if top == 'Minecraft_Java_Server_Client' and name.endswith('_mappings.txt'):
            return True
        if top == 'Minecraft_MCP_Mappings' and suffix == '.csv':
            return True
    return False


def iter_text_files(source: SourceSpec, skipped: list[tuple[str, str]] | None = None) -> Iterable[Path]:
    root = source.root
    def onerror(exc: OSError):
        if skipped is not None:
            skipped.append((getattr(exc, 'filename', '') or str(root), f'os.walk: {exc}'))
    for current, dirs, names in os.walk(root, onerror=onerror, followlinks=False):
        c = Path(current)
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith('.git')]
        if not source.external and c == root:
            dirs[:] = [d for d in dirs if d not in {'Index', 'Minecraft_Mappings_Corpus'}]
        for name in names:
            p = c / name
            if not (name in SPECIAL_NAMES or p.suffix.lower() in TEXT_EXTENSIONS):
                continue
            if is_dedicated_mapping_source(source, p):
                continue
            try:
                st = p.stat()
            except (FileNotFoundError, PermissionError, OSError) as exc:
                if skipped is not None:
                    skipped.append((str(p), f'stat: {exc}'))
                continue
            if st.st_size > MAX_FILE_SIZE:
                continue
            try:
                if p.is_symlink():
                    continue
            except OSError:
                continue
            yield p


def chunks_from_text(text: str):
    lines = text.splitlines()
    if not lines:
        yield 1, 1, ''
        return
    i = 0
    while i < len(lines):
        start = i
        buf: list[str] = []
        chars = 0
        while i < len(lines) and (i - start) < CHUNK_LINES and chars < CHUNK_CHARS:
            line = lines[i]
            buf.append(line); chars += len(line) + 1; i += 1
        yield start + 1, i, '\n'.join(buf)


def remove_db_family(path: Path) -> None:
    for p in (path, Path(str(path) + '-wal'), Path(str(path) + '-shm')):
        try: p.unlink()
        except (FileNotFoundError, PermissionError, OSError): pass


def active_db_path(canonical: Path) -> Path:
    pointer = canonical.parent / '_ACTIVE_DB.txt'
    try:
        name = pointer.read_text(encoding='utf-8-sig').strip()
    except (FileNotFoundError, OSError):
        name = ''
    if name:
        candidate = (canonical.parent / name).resolve()
        try:
            candidate.relative_to(canonical.parent.resolve())
        except ValueError:
            return canonical
        if candidate.exists():
            return candidate
    return canonical


def write_active_pointer(canonical: Path, active: Path) -> None:
    tmp = canonical.parent / '_ACTIVE_DB.txt.tmp'
    tmp.write_text(active.name + '\n', encoding='utf-8')
    os.replace(tmp, canonical.parent / '_ACTIVE_DB.txt')


def cleanup_inactive_dbs(canonical: Path, active: Path) -> None:
    for p in canonical.parent.glob('knowledge*.db'):
        if p.resolve() == active.resolve():
            continue
        remove_db_family(p)


def get_schema_version(path: Path) -> int:
    if not path.exists(): return 0
    try:
        with sqlite3.connect(path) as c:
            return int(c.execute('PRAGMA user_version').fetchone()[0])
    except sqlite3.DatabaseError:
        return -1


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.execute('PRAGMA temp_store=MEMORY')
    conn.execute('PRAGMA foreign_keys=ON')
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY,
            path TEXT UNIQUE NOT NULL,
            category TEXT,
            version TEXT,
            sha256 TEXT NOT NULL,
            mtime_ns INTEGER NOT NULL,
            size INTEGER NOT NULL,
            physical_path TEXT UNIQUE NOT NULL,
            source_id TEXT NOT NULL,
            source_root TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY,
            file_id INTEGER NOT NULL,
            chunk_no INTEGER NOT NULL,
            start_line INTEGER NOT NULL,
            end_line INTEGER NOT NULL,
            FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            content,
            chunk_id UNINDEXED,
            tokenize='unicode61'
        );
        CREATE INDEX IF NOT EXISTS idx_files_category_version ON files(category, version);
        CREATE INDEX IF NOT EXISTS idx_files_source_physical ON files(source_id, physical_path);
        CREATE INDEX IF NOT EXISTS idx_chunks_file ON chunks(file_id);
    ''')
    conn.execute(f'PRAGMA user_version={SCHEMA_VERSION}')


def load_external_sources(manifest_path: Path) -> list[SourceSpec]:
    if not manifest_path.exists(): return []
    try:
        data = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    except Exception as exc:
        raise RuntimeError(f'Invalid external source manifest {manifest_path}: {exc}') from exc
    result: list[SourceSpec] = []
    seen: set[str] = set()
    for item in data.get('sources', []):
        if not item.get('index_in_place', True): continue
        sid = str(item.get('id', '')).strip(); path_text = str(item.get('path', '')).strip()
        cat = str(item.get('category', 'External')).strip() or 'External'
        if not sid or not path_text: continue
        if sid in seen: raise RuntimeError(f'Duplicate external source id in {manifest_path}: {sid}')
        seen.add(sid); result.append(SourceSpec(sid, Path(path_text).expanduser(), cat, True))
    return result


def display_path_for(source: SourceSpec, path: Path) -> str:
    return str(path.resolve()) if source.external else str(path.relative_to(source.root)).replace('\\', '/')


def delete_file_ids(conn: sqlite3.Connection, ids: list[int]) -> None:
    if not ids: return
    for i in range(0, len(ids), 500):
        batch = ids[i:i+500]
        q = ','.join('?' for _ in batch)
        chunk_ids = [int(r[0]) for r in conn.execute(f"SELECT id FROM chunks WHERE file_id IN ({q})", batch)]
        for j in range(0, len(chunk_ids), 500):
            cb = chunk_ids[j:j+500]
            cq = ','.join('?' for _ in cb)
            conn.execute(f'DELETE FROM chunks_fts WHERE CAST(chunk_id AS INTEGER) IN ({cq})', cb)
        conn.execute(f'DELETE FROM files WHERE id IN ({q})', batch)


def reconcile_source(conn: sqlite3.Connection, source_id: str, quiet: bool) -> int:
    stale = [int(r[0]) for r in conn.execute('''
        SELECT f.id FROM files f
        WHERE f.source_id=? AND NOT EXISTS(
            SELECT 1 FROM temp.seen_paths s WHERE s.source_id=f.source_id AND s.physical_path=f.physical_path
        )
    ''', (source_id,))]
    if stale and not quiet:
        print(f'[index] {source_id}: reconciling {len(stale):,} removed file(s)...', flush=True)
    removed = 0
    for i in range(0, len(stale), 1000):
        batch = stale[i:i+1000]
        delete_file_ids(conn, batch)
        removed += len(batch)
        if not quiet:
            print(f'[index] {source_id}: reconciled {removed:,}/{len(stale):,} removed files', flush=True)
    return removed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True); ap.add_argument('--db', required=True)
    ap.add_argument('--sources-manifest', default=''); ap.add_argument('--quiet', action='store_true')
    ap.add_argument('--force-rebuild', action='store_true')
    args = ap.parse_args()

    root = Path(args.root).resolve(); canonical_db = Path(args.db).resolve(); canonical_db.parent.mkdir(parents=True, exist_ok=True)
    manifest = Path(args.sources_manifest).resolve() if args.sources_manifest else root / 'external_sources.json'

    current_db = active_db_path(canonical_db)
    old_schema = get_schema_version(current_db)
    migrating = args.force_rebuild or old_schema != SCHEMA_VERSION
    if migrating:
        if current_db.exists() and not args.quiet:
            print(f'[index] Lock-safe compact schema migration v{old_schema} -> v{SCHEMA_VERSION}. Building a new derived DB beside the old one.', flush=True)
        db = canonical_db.parent / f'knowledge.v{SCHEMA_VERSION}.{int(__import__("time").time())}.db'
        remove_db_family(db)
    else:
        db = current_db

    sources = [SourceSpec('local', root, None, False)] + load_external_sources(manifest)
    active = {s.source_id for s in sources}
    conn = sqlite3.connect(db)
    init_db(conn)
    conn.execute('CREATE TEMP TABLE seen_paths(source_id TEXT NOT NULL, physical_path TEXT NOT NULL, PRIMARY KEY(source_id,physical_path)) WITHOUT ROWID')

    changed = indexed = scanned = removed_total = 0
    skipped: list[tuple[str, str]] = []
    scanned_ids: set[str] = set()

    for source in sources:
        source_root = source.root.resolve()
        if not source_root.exists() or not source_root.is_dir():
            skipped.append((str(source.root), f'source unavailable: {source.source_id}'))
            if not args.quiet: print(f'[index] SKIP source {source.source_id}: unavailable at {source.root}', flush=True)
            continue
        scanned_ids.add(source.source_id)
        source_scanned = source_changed = 0
        spec = SourceSpec(source.source_id, source_root, source.category, source.external)
        if not args.quiet: print(f'[index] Scanning source {source.source_id}: {source_root}', flush=True)

        for path in iter_text_files(spec, skipped):
            scanned += 1; source_scanned += 1
            if not args.quiet and source_scanned % 1000 == 0:
                print(f'[index] {source.source_id}: scanned {source_scanned:,}; changed {source_changed:,}; total {scanned:,}', flush=True)
            try:
                physical = str(path.resolve()); display = display_path_for(spec, path); st = path.stat()
            except (ValueError, OSError) as exc:
                skipped.append((str(path), f'resolve/stat: {exc}')); continue
            conn.execute('INSERT OR IGNORE INTO temp.seen_paths(source_id,physical_path) VALUES(?,?)', (source.source_id, physical))
            row = conn.execute('SELECT id,sha256,mtime_ns,size,category,version FROM files WHERE physical_path=?', (physical,)).fetchone()
            category, version = classify_source(spec, path)
            if row and int(row[3]) == st.st_size and int(row[2]) == st.st_mtime_ns:
                if (row[4] or '') != category or (row[5] or '') != version:
                    conn.execute('UPDATE files SET category=?,version=? WHERE id=?', (category, version, row[0]))
                    changed += 1; source_changed += 1
                    if source_changed % 100 == 0:
                        conn.commit()
                indexed += 1
                continue
            try: digest = file_hash(path)
            except (FileNotFoundError, PermissionError, OSError) as exc:
                skipped.append((str(path), f'hash: {exc}')); continue
            if row and row[1] == digest:
                conn.execute('UPDATE files SET mtime_ns=?,size=?,category=?,version=? WHERE id=?', (st.st_mtime_ns, st.st_size, category, version, row[0]))
                indexed += 1; continue
            try: text = path.read_text(encoding='utf-8', errors='replace')
            except Exception as exc:
                skipped.append((str(path), f'read: {exc}')); continue

            if row:
                fid = int(row[0])
                old_chunk_ids = [int(r[0]) for r in conn.execute('SELECT id FROM chunks WHERE file_id=?', (fid,))]
                if old_chunk_ids:
                    q = ','.join('?' for _ in old_chunk_ids)
                    conn.execute(f'DELETE FROM chunks_fts WHERE CAST(chunk_id AS INTEGER) IN ({q})', old_chunk_ids)
                conn.execute('DELETE FROM chunks WHERE file_id=?', (fid,))
                conn.execute('''UPDATE files SET path=?,category=?,version=?,sha256=?,mtime_ns=?,size=?,source_id=?,source_root=? WHERE id=?''',
                             (display, category, version, digest, st.st_mtime_ns, st.st_size, source.source_id, str(source_root), fid))
            else:
                conflict = conn.execute('SELECT id FROM files WHERE path=?', (display,)).fetchone()
                if conflict: delete_file_ids(conn, [int(conflict[0])])
                cur = conn.execute('''INSERT INTO files(path,category,version,sha256,mtime_ns,size,physical_path,source_id,source_root)
                                      VALUES(?,?,?,?,?,?,?,?,?)''',
                                   (display, category, version, digest, st.st_mtime_ns, st.st_size, physical, source.source_id, str(source_root)))
                fid = int(cur.lastrowid)
            for n, (start, end, content) in enumerate(chunks_from_text(text)):
                cur_chunk = conn.execute('INSERT INTO chunks(file_id,chunk_no,start_line,end_line) VALUES(?,?,?,?)', (fid, n, start, end))
                chunk_id = int(cur_chunk.lastrowid)
                conn.execute('INSERT INTO chunks_fts(content,chunk_id) VALUES(?,?)', (content, str(chunk_id)))
            changed += 1; source_changed += 1; indexed += 1
            if source_changed % 100 == 0:
                conn.commit()

        if not args.quiet: print(f'[index] {source.source_id}: scan complete; reconciling deletions...', flush=True)
        removed = reconcile_source(conn, source.source_id, args.quiet); removed_total += removed
        conn.execute('DELETE FROM temp.seen_paths WHERE source_id=?', (source.source_id,))
        conn.commit()
        conn.execute('PRAGMA wal_checkpoint(PASSIVE)')
        if not args.quiet:
            print(f'[index] Completed source {source.source_id}: scanned {source_scanned:,}, changed {source_changed:,}, removed {removed:,}', flush=True)

    # Unregistered sources are stale by definition; registered but offline sources are retained.
    unregistered = [int(r[0]) for r in conn.execute('SELECT id FROM files WHERE source_id NOT IN (%s)' % ','.join('?' for _ in active), tuple(active))] if active else []
    if unregistered:
        if not args.quiet: print(f'[index] Removing {len(unregistered):,} file(s) from unregistered source(s)...', flush=True)
        delete_file_ids(conn, unregistered); removed_total += len(unregistered); conn.commit()

    counts = {
        'schema': SCHEMA_VERSION,
        'files': conn.execute('SELECT COUNT(*) FROM files').fetchone()[0],
        'chunks': conn.execute('SELECT COUNT(*) FROM chunks').fetchone()[0],
        'scanned_this_run': scanned, 'changed_this_run': changed, 'removed_this_run': removed_total,
        'indexed_this_run': indexed, 'skipped_this_run': len(skipped),
        'sources_registered': len(sources), 'sources_scanned': len(scanned_ids),
        'external_files': conn.execute("SELECT COUNT(*) FROM files WHERE source_id<>'local'").fetchone()[0],
        'compact_content_storage': True, 'mapping_text_excluded': True,
    }
    conn.commit(); conn.execute('PRAGMA wal_checkpoint(TRUNCATE)'); conn.close()

    if migrating:
        write_active_pointer(canonical_db, db)
        if not args.quiet: print(f'[index] Activated compact DB: {db.name}', flush=True)
        cleanup_inactive_dbs(canonical_db, db)

    skip_log = db.parent / 'index_skipped_paths.log'
    if skipped:
        with skip_log.open('w', encoding='utf-8', errors='replace') as fh:
            for p, reason in skipped: fh.write(f'{p}\t{reason}\n')
    else:
        try: skip_log.unlink()
        except FileNotFoundError: pass
    if not args.quiet:
        print(f'[index] Complete: {json.dumps(counts)}', flush=True)
        if skipped: print(f'[index] Skipped paths log: {skip_log}', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
