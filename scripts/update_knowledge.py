#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

MOJANG_MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"

LEGACY_MCP_1122_URL = "https://mcpbot.unascribed.com/mcp_stable/39-1.12/mcp_stable-39-1.12.zip"

REPOS = {
    "neoforge_primers": "https://github.com/neoforged/.github.git",
    "mcpconfig": "https://github.com/MinecraftForge/MCPConfig.git",
    "neoforge_docs": "https://github.com/neoforged/Documentation.git",
    "neoforge": "https://github.com/neoforged/NeoForge.git",
    "neoform": "https://github.com/neoforged/NeoForm.git",
    "moddevgradle": "https://github.com/neoforged/ModDevGradle.git",
    "forge": "https://github.com/MinecraftForge/MinecraftForge.git",
    "gradle": "https://github.com/gradle/gradle.git",
    "geckolib": "https://github.com/bernie-g/geckolib.git",
    "mcreator": "https://github.com/MCreator/MCreator.git",
}

TEXT_STATUS = {
    "source": "RBLocalLLM updater",
    "generated": True,
    "zero_copy": True,
}

# v1.2.13 and earlier generated these mirrors from knowledge/_upstream.
# They are safe to remove because the Git checkout is the canonical source.
LEGACY_REFERENCE_MIRRORS = (
    Path("References/NeoForge/Documentation"),
    Path("References/NeoForge/NeoForge"),
    Path("References/NeoForge/NeoForm"),
    Path("References/NeoForge/ModDevGradle"),
    Path("References/Forge/MinecraftForge"),
    Path("References/Gradle/Gradle"),
    Path("References/GeckoLib/GeckoLib"),
)


def log(msg: str, quiet: bool = False) -> None:
    if not quiet:
        print(msg, flush=True)


def run(cmd: list[str], cwd: Path | None = None, quiet: bool = False) -> None:
    """Run a native command and use its real exit code as the source of truth."""
    if not quiet:
        print(">", " ".join(cmd), flush=True)

    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if proc.stdout and not quiet:
        print(proc.stdout.rstrip(), flush=True)

    if proc.returncode != 0:
        detail = proc.stdout.strip() if proc.stdout else ""
        raise RuntimeError(
            f"Command failed ({proc.returncode}): {' '.join(cmd)}"
            + (f"\n{detail}" if detail else "")
        )


def fetch_json(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "RBLocalLLM/1.2.22"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def sha1_file(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def load_verify_cache(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
    except Exception:
        return {}


def save_verify_cache(path: Path, data: dict[str, Any]) -> None:
    write_json(path, data)


def download_verified(url: str, dest: Path, sha1: str | None, size: int | None, quiet: bool,
                      verify_cache: dict[str, Any] | None = None) -> bool:
    """Download immutable Mojang artifacts only when absent/invalid.

    Existing files use size + persisted verified SHA1 state for O(1) checks. A legacy file
    without cached state is hashed once, then future updates skip re-hashing it.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    key = str(dest.resolve())
    cached = (verify_cache or {}).get(key, {}) if verify_cache is not None else {}
    if dest.exists():
        actual_size = dest.stat().st_size
        if size is not None and actual_size != size:
            pass
        elif sha1 and cached.get("sha1", "").lower() == sha1.lower() and cached.get("size") == actual_size:
            log(f"Cached/unchanged: {dest}", quiet)
            return False
        elif sha1:
            digest = sha1_file(dest).lower()
            if digest == sha1.lower():
                if verify_cache is not None:
                    verify_cache[key] = {"sha1": digest, "size": actual_size, "verified_unix": int(time.time())}
                log(f"Verified existing once: {dest}", quiet)
                return False
        else:
            return False

    tmp = dest.with_suffix(dest.suffix + ".part")
    if tmp.exists(): tmp.unlink()
    log(f"Downloading {url} -> {dest}", quiet)
    req = urllib.request.Request(url, headers={"User-Agent": "RBLocalLLM/1.2.22"})
    with urllib.request.urlopen(req, timeout=300) as r, tmp.open("wb") as out:
        shutil.copyfileobj(r, out, length=1024 * 1024)
    if size is not None and tmp.stat().st_size != size:
        tmp.unlink(missing_ok=True); raise RuntimeError(f"Size mismatch for {dest}")
    digest = sha1_file(tmp).lower() if sha1 else None
    if sha1 and digest != sha1.lower():
        tmp.unlink(missing_ok=True); raise RuntimeError(f"SHA1 mismatch for {dest}")
    os.replace(tmp, dest)
    if verify_cache is not None and sha1:
        verify_cache[key] = {"sha1": sha1.lower(), "size": dest.stat().st_size, "verified_unix": int(time.time())}
    return True


def version_tuple(v: str) -> tuple[int, ...] | None:
    if not re.fullmatch(r"\d+(?:\.\d+)*", v):
        return None
    return tuple(int(p) for p in v.split("."))


def version_in_range(v: str, low: str, high: str | None = None) -> bool:
    t = version_tuple(v)
    lo = version_tuple(low)
    hi = version_tuple(high) if high else None
    if t is None or lo is None:
        return False
    if t < lo:
        return False
    if hi is not None and t > hi:
        return False
    return True


def update_git_repo(name: str, url: str, upstream: Path, quiet: bool) -> Path:
    dst = upstream / name
    if not dst.exists():
        run(["git", "clone", "--filter=blob:none", url, str(dst)], quiet=quiet)
    else:
        try:
            run(["git", "-C", str(dst), "fetch", "--all", "--prune"], quiet=quiet)
            run(["git", "-C", str(dst), "pull", "--ff-only"], quiet=quiet)
        except Exception:
            # Keep the last known good checkout; surface warning but continue.
            log(f"WARNING: Git update failed for {name}; retaining existing checkout.", quiet=False)
    return dst


def write_json(path: Path, data: Any) -> bool:
    """Write JSON only when content changed so incremental indexing can trust mtime."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(data, indent=2, sort_keys=True)
    try:
        if path.exists() and path.read_text(encoding="utf-8-sig") == rendered:
            return False
    except Exception:
        pass
    path.write_text(rendered, encoding="utf-8")
    return True


def _rmtree_onerror(func, path, exc_info):
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        raise exc_info[1]


def remove_tree(path: Path, quiet: bool, label: str) -> None:
    if not path.exists():
        return
    log(f"Removing legacy duplicate {label}: {path}", quiet)
    shutil.rmtree(path, onerror=_rmtree_onerror)


def is_generated_status(folder: Path) -> bool:
    status = folder / "_STATUS.json"
    if not status.exists():
        return False
    try:
        data = json.loads(status.read_text(encoding="utf-8-sig"))
    except Exception:
        return False
    return data.get("source") == "RBLocalLLM updater" and bool(data.get("generated"))


def prune_empty_parents(path: Path, stop: Path) -> None:
    current = path
    stop = stop.resolve()
    while current.exists() and current.resolve() != stop:
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def remove_generated_duplicate_mirrors(root: Path, quiet: bool) -> dict[str, int]:
    """Remove only mirrors created by older RBLocalLLM updater/installer versions."""
    removed = {"reference_mirrors": 0, "primer_mirrors": 0, "mapping_mirrors": 0, "completed_project_mirrors": 0}

    for rel in LEGACY_REFERENCE_MIRRORS:
        target = root / rel
        if target.exists():
            remove_tree(target, quiet, "Git reference mirror")
            removed["reference_mirrors"] += 1
            prune_empty_parents(target.parent, root)

    # v1.2.13 imported H:\GrokBuild_MF\Completed_Projects into this exact path.
    legacy_completed = root / "Gradle_Workspaces" / "Completed_Projects"
    if legacy_completed.exists():
        remove_tree(legacy_completed, quiet, "completed-project copy")
        removed["completed_project_mirrors"] += 1

    # NeoForge_Primers directories generated by old updaters contained copied files.
    primers_root = root / "NeoForge_Primers"
    if primers_root.exists():
        for child in list(primers_root.iterdir()):
            if child.is_dir() and is_generated_status(child):
                remove_tree(child, quiet, "primer mirror")
                removed["primer_mirrors"] += 1

    # Preserve any user-authored mapping files, but remove known generated copies.
    mappings_root = root / "Minecraft_MCP_Mappings"
    if mappings_root.exists():
        for child in mappings_root.iterdir():
            if not child.is_dir() or not is_generated_status(child):
                continue
            mcp_copy = child / "MCPConfig"
            if mcp_copy.exists():
                remove_tree(mcp_copy, quiet, "MCPConfig mirror")
                removed["mapping_mirrors"] += 1
            for name in ("mojang_client_mappings.txt", "mojang_server_mappings.txt", "mojang_version.json"):
                p = child / name
                if p.exists():
                    log(f"Removing duplicate Mojang mapping metadata: {p}", quiet)
                    p.unlink()
                    removed["mapping_mirrors"] += 1

    return removed


def ensure_legacy_mcp_1122(mappings_root: Path, quiet: bool) -> None:
    """Download the canonical MCP stable_39 CSV export once for 1.12.2 readable names."""
    dest = mappings_root / "1.12.2" / "mcp_stable_39"
    required = [dest / "fields.csv", dest / "methods.csv", dest / "params.csv"]
    if all(p.exists() for p in required):
        return
    dest.mkdir(parents=True, exist_ok=True)
    archive = dest / "mcp_stable-39-1.12.zip"
    if not archive.exists():
        log(f"Downloading legacy MCP stable_39 mappings -> {archive}", quiet)
        req = urllib.request.Request(LEGACY_MCP_1122_URL, headers={"User-Agent": "RBLocalLLM/1.2.22"})
        tmp = archive.with_suffix('.zip.part')
        with urllib.request.urlopen(req, timeout=180) as r, tmp.open('wb') as out:
            shutil.copyfileobj(r, out, length=1024 * 1024)
        os.replace(tmp, archive)
    with zipfile.ZipFile(archive) as zf:
        names = {Path(n).name: n for n in zf.namelist()}
        for name in ("fields.csv", "methods.csv", "params.csv"):
            if name not in names:
                raise RuntimeError(f"Legacy MCP archive missing {name}: {archive}")
            target = dest / name
            with zf.open(names[name]) as src, target.open('wb') as out:
                shutil.copyfileobj(src, out)
    write_json(dest / "_SOURCE.json", {
        **TEXT_STATUS,
        "version": "1.12.2",
        "mapping": "MCP stable_39 for Minecraft 1.12",
        "canonical_path": str(dest),
        "download_url": LEGACY_MCP_1122_URL,
        "note": "Human-readable MCP field/method/parameter names used with MCPConfig joined.tsrg for legacy 1.12.2 deobfuscation.",
    })


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--include-snapshots", action="store_true")
    ap.add_argument("--include-server-artifacts", action="store_true", help="Also retain/download dedicated server JARs and Mojang server mappings")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--cleanup-only", action="store_true", help="Remove legacy generated mirrors without network access")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    upstream = root / "_upstream"
    upstream.mkdir(parents=True, exist_ok=True)

    primers_root = root / "NeoForge_Primers"
    mappings_root = root / "Minecraft_MCP_Mappings"
    mc_root = root / "Minecraft_Java_Server_Client"
    for p in (primers_root, mappings_root, mc_root):
        p.mkdir(parents=True, exist_ok=True)

    verify_cache_path = upstream / "download_verify_cache.json"
    verify_cache = load_verify_cache(verify_cache_path)

    cleanup = remove_generated_duplicate_mirrors(root, args.quiet)
    if args.cleanup_only:
        log(f"Legacy duplicate cleanup complete: {cleanup}", args.quiet)
        return 0

    try:
        ensure_legacy_mcp_1122(mappings_root, args.quiet)
    except Exception as e:
        log(f"WARNING: Unable to update legacy MCP 1.12.2 mapping CSVs: {e}", False)

    # Git working trees under _upstream are canonical. They are indexed directly.
    checkouts: dict[str, Path] = {}
    for name, url in REPOS.items():
        try:
            checkouts[name] = update_git_repo(name, url, upstream, args.quiet)
        except Exception as e:
            log(f"WARNING: Unable to clone/update {name}: {e}", False)

    manifest = fetch_json(MOJANG_MANIFEST)
    write_json(upstream / "mojang_version_manifest_v2.json", manifest)
    releases = [
        v for v in manifest.get("versions", [])
        if v.get("type") == "release" and version_in_range(v.get("id", ""), "1.12")
    ]
    snapshots = [v for v in manifest.get("versions", []) if v.get("type") != "release"] if args.include_snapshots else []
    selected_versions = releases + snapshots

    # Version-oriented primer folders are pointer metadata only; no source files are copied.
    primer_checkout = checkouts.get("neoforge_primers")
    official_primers: dict[str, Path] = {}
    if primer_checkout:
        psrc = primer_checkout / "primers"
        if psrc.exists():
            official_primers = {child.name: child.resolve() for child in psrc.iterdir() if child.is_dir()}

    primer_names = {v["id"] for v in releases} | set(official_primers)
    for vid in sorted(primer_names, key=lambda v: version_tuple(v) or (999999,)):
        dest = primers_root / vid
        dest.mkdir(parents=True, exist_ok=True)
        canonical = official_primers.get(vid)
        status = {
            **TEXT_STATUS,
            "version": vid,
            "official_primer": canonical is not None,
            "indexed_in_place": canonical is not None,
            "canonical_path": str(canonical) if canonical else None,
            "upstream": REPOS["neoforge_primers"] if canonical else None,
            "upstream_path": f"primers/{vid}" if canonical else None,
            "note": None if canonical else "No official NeoForged primer folder with this exact version name was present at the last update.",
        }
        write_json(dest / "_STATUS.json", status)

    # MCPConfig is also indexed directly from _upstream. Keep only pointer/status metadata here.
    mcp_checkout = checkouts.get("mcpconfig")
    mcp_release = mcp_checkout / "versions" / "release" if mcp_checkout else None

    # Mojang client/server JARs and official mappings live only here. There is no second copy
    # under Minecraft_MCP_Mappings.
    for entry in selected_versions:
        vid = entry.get("id")
        if not vid:
            continue
        if entry.get("type") != "release" and not args.include_snapshots:
            continue
        if entry.get("type") == "release" and not version_in_range(vid, "1.12"):
            continue

        vdir = mc_root / vid
        vdir.mkdir(parents=True, exist_ok=True)
        version_json = vdir / "version.json"
        source_json = vdir / "_SOURCE.json"
        cached_source = {}
        try:
            cached_source = json.loads(source_json.read_text(encoding="utf-8-sig")) if source_json.exists() else {}
        except Exception:
            cached_source = {}
        meta_cached = bool(version_json.exists() and entry.get("sha1") and
                           cached_source.get("version_manifest_sha1") == entry.get("sha1"))
        if meta_cached:
            meta = json.loads(version_json.read_text(encoding="utf-8-sig"))
            log(f"Cached version metadata: {vid}", args.quiet)
        else:
            meta = fetch_json(entry["url"])
            write_json(version_json, meta)
        source_updated = cached_source.get("updated_unix") if meta_cached else int(time.time())
        write_json(source_json, {
            "version": vid,
            "type": entry.get("type"),
            "version_manifest_sha1": entry.get("sha1"),
            "version_json_url": entry.get("url"),
            "updated_unix": source_updated,
            "canonical_mojang_location": True,
        })

        downloads = meta.get("downloads", {})
        # v1.2.22 defaults to a client-focused corpus.  The Minecraft client JAR
        # already carries the common/runtime code needed for client-side modding,
        # while dedicated-server artifacts add a large, overlapping mapping set.
        # Server artifacts remain an explicit opt-in for users who build dedicated
        # server mods or need server-only classes.
        targets = {
            "client": "client.jar",
            "client_mappings": "client_mappings.txt",
        }
        if args.include_server_artifacts:
            targets.update({
                "server": "server.jar",
                "server_mappings": "server_mappings.txt",
            })
        else:
            for obsolete_name in ("server.jar", "server_mappings.txt"):
                obsolete = vdir / obsolete_name
                if obsolete.exists():
                    try:
                        obsolete.unlink()
                        verify_cache.pop(str(obsolete.resolve()), None)
                        log(f"Pruned client-only unused artifact: {obsolete}", args.quiet)
                    except PermissionError:
                        log(f"WARNING: Could not prune locked server artifact: {obsolete}", False)

        for key, filename in targets.items():
            d = downloads.get(key)
            if not d:
                continue
            try:
                download_verified(d["url"], vdir / filename, d.get("sha1"), d.get("size"), args.quiet, verify_cache)
            except Exception as e:
                log(f"WARNING: {vid} {key}: {e}", False)

        if entry.get("type") == "release" and version_in_range(vid, "1.20.1", "1.21.11"):
            mdir = mappings_root / vid
            mdir.mkdir(parents=True, exist_ok=True)
            mcp_path = (mcp_release / vid).resolve() if mcp_release and (mcp_release / vid).is_dir() else None
            status = {
                **TEXT_STATUS,
                "version": vid,
                "mcpconfig": mcp_path is not None,
                "mcpconfig_canonical_path": str(mcp_path) if mcp_path else None,
                "mcpconfig_indexed_in_place": mcp_path is not None,
                "mojang_mappings": (vdir / "client_mappings.txt").exists() or (args.include_server_artifacts and (vdir / "server_mappings.txt").exists()),
                "mojang_canonical_root": str(vdir.resolve()),
                "mojang_client_mappings": str((vdir / "client_mappings.txt").resolve()) if (vdir / "client_mappings.txt").exists() else None,
                "mojang_server_mappings": str((vdir / "server_mappings.txt").resolve()) if args.include_server_artifacts and (vdir / "server_mappings.txt").exists() else None,
                "mapping_profile": "client+server" if args.include_server_artifacts else "client-only",
                "mojang_mapping_copy_count": 1,
            }
            write_json(mdir / "_STATUS.json", status)

    # Ensure pointer folders exist even if a specific version download/update failed.
    for v in releases:
        vid = v["id"]
        if not version_in_range(vid, "1.20.1", "1.21.11"):
            continue
        status_path = mappings_root / vid / "_STATUS.json"
        if status_path.exists():
            continue
        vdir = mc_root / vid
        mcp_path = (mcp_release / vid).resolve() if mcp_release and (mcp_release / vid).is_dir() else None
        write_json(status_path, {
            **TEXT_STATUS,
            "version": vid,
            "mcpconfig": mcp_path is not None,
            "mcpconfig_canonical_path": str(mcp_path) if mcp_path else None,
            "mcpconfig_indexed_in_place": mcp_path is not None,
            "mojang_mappings": False,
            "mojang_canonical_root": str(vdir.resolve()),
            "mojang_mapping_copy_count": 1,
            "note": "Pointer folder created; Mojang mapping content was not available at the last update.",
        })

    save_verify_cache(verify_cache_path, verify_cache)

    repo_paths = {name: str(path.resolve()) for name, path in checkouts.items()}
    write_json(root / "knowledge_manifest.json", {
        "schema": 2,
        "updated_unix": int(time.time()),
        "zero_copy": True,
        "latest_release": manifest.get("latest", {}).get("release"),
        "latest_snapshot": manifest.get("latest", {}).get("snapshot"),
        "include_snapshots": bool(args.include_snapshots),
        "mapping_profile": "client+server" if args.include_server_artifacts else "client-only",
        "include_server_artifacts": bool(args.include_server_artifacts),
        "repositories": REPOS,
        "repository_paths": repo_paths,
        "repository_policy": "knowledge/_upstream working trees are canonical and indexed directly; generated mirrors are not created",
        "primer_root": str(primers_root),
        "mapping_root": str(mappings_root),
        "minecraft_root": str(mc_root),
        "mojang_mapping_policy": "single canonical copy under Minecraft_Java_Server_Client/<version>",
        "legacy_duplicate_cleanup": cleanup,
    })
    log("Knowledge source update complete (zero-copy mode).", args.quiet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
