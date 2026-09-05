#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime
import json
import os
import sqlite3
import time
import urllib.error
import urllib.request
from pathlib import Path

# GokuAI alias proxy (:11437) accepts these; only one EXL3 worker is loaded at a time.
ALIASES = ["goku-fast", "goku-code", "goku-heavy", "goku-research", "goku-reviewer"]
TOKEN_LIMITS = {
    "goku-fast": 900,
    "goku-code": 900,
    "goku-heavy": 1400,
    "goku-research": 1400,
    "goku-reviewer": 1400,
}


def resolve_active_db(folder: Path, canonical_name: str) -> Path:
    pointer = folder / "_ACTIVE_DB.txt"
    if pointer.exists():
        try:
            name = pointer.read_text(encoding="utf-8-sig").strip()
            candidate = (folder / name).resolve()
            candidate.relative_to(folder.resolve())
            if candidate.exists():
                return candidate
        except Exception:
            pass
    return folder / canonical_name


def mapping_evidence(root: Path) -> dict:
    db = resolve_active_db(root / "Minecraft_Mappings_Corpus", "mappings.db")
    result = {"available": False, "db": str(db)}
    if not db.exists():
        return result
    try:
        with sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True) as c:
            row = c.execute(
                """SELECT minecraft_version,namespace_from,namespace_to,kind,
                          COALESCE(owner_from,''),COALESCE(owner_to,''),name_from,name_to
                   FROM symbols
                   WHERE name_from<>name_to AND length(name_from)>1 AND length(name_to)>1
                   ORDER BY CASE WHEN minecraft_version='1.12.2' THEN 0 ELSE 1 END, id
                   LIMIT 1"""
            ).fetchone()
        if row:
            result.update({
                "available": True,
                "version": row[0], "namespace_from": row[1], "namespace_to": row[2],
                "kind": row[3], "owner_from": row[4], "owner_to": row[5],
                "name_from": row[6], "name_to": row[7],
            })
    except Exception as exc:
        result["error"] = str(exc)
    return result


def tests_for(root: Path) -> list[dict]:
    mapping = mapping_evidence(root)
    tests = []
    if mapping.get("available"):
        tests.append({
            "id": "mapping_grounded",
            "weight": 25,
            "prompt": (
                "Use ONLY the evidence below. Return JSON only with keys mapped_name, namespace, confidence. "
                "Do not infer any other Minecraft version facts.\n"
                f"Evidence: Minecraft {mapping['version']}; {mapping['kind']} mapping; "
                f"{mapping['namespace_from']} name={mapping['name_from']!r}; "
                f"{mapping['namespace_to']} name={mapping['name_to']!r}.\n"
                f"Question: What is the {mapping['namespace_to']} name for {mapping['name_from']!r}?"
            ),
            "expected": {"contains": [mapping["name_to"], mapping["namespace_to"]], "forbid": []},
        })
    else:
        tests.append({
            "id": "mapping_grounded",
            "weight": 25,
            "prompt": (
                "Return JSON only with keys mapped_name, namespace, confidence. Evidence: Minecraft 1.12.2, "
                "SRG name func_184185_a maps to MCP-readable name collideWithNearbyEntities. "
                "Question: What MCP-readable name is provided by the evidence?"
            ),
            "expected": {"contains": ["collideWithNearbyEntities", "mcp"], "forbid": []},
        })

    tests.extend([
        {
            "id": "version_guardrail",
            "weight": 20,
            "prompt": (
                "Return JSON only with keys answer, unsupported_claims, confidence. "
                "Evidence provided: source project is Forge 1.20.1; target is NeoForge 26.2. "
                "No evidence states which Minecraft release NeoForge 26.2 corresponds to. "
                "Question: Which Minecraft release is NeoForge 26.2 based on? If the evidence does not establish it, say unknown/not provided."
            ),
            "expected": {"contains_any": ["unknown", "not provided", "not established", "insufficient"],
                         "forbid": ["1.20.2"]},
        },
        {
            "id": "gradle_discipline",
            "weight": 20,
            "prompt": (
                "Return JSON only with keys diagnosis, next_checks, invented_dependency, confidence. "
                "Gradle says only: 'Could not resolve all files for configuration'. No artifact name or repository error is supplied. "
                "Give the next diagnostic steps. Do not invent a dependency name. Set invented_dependency to null."
            ),
            "expected": {"contains_any": ["artifact", "dependency", "configuration"],
                         "contains": ["invented_dependency"], "forbid": ["examplemod", "jei", "geckolib"]},
        },
        {
            "id": "migration_scope",
            "weight": 20,
            "prompt": (
                "Return JSON only with keys task, evidence_needed, validation, confidence. Scope exactly ONE task: "
                "port a single Forge 1.20.1 entity registration class to NeoForge 26.2. "
                "Require source code plus target API evidence and make compilation the primary validation. Do not claim the code is already correct."
            ),
            "expected": {"contains": ["evidence_needed", "validation"],
                         "contains_any": ["compile", "compilation", "gradle"], "forbid": []},
        },
        {
            "id": "asset_preservation",
            "weight": 15,
            "prompt": (
                "Return JSON only with keys checks, preserve, confidence. For Minecraft mod asset migration, give concise checks for "
                "textures, model/UV geometry, animations and OGG sounds. Explicitly preserve original artistic content."
            ),
            "expected": {"contains": ["checks", "preserve"],
                         "contains_any_groups": [["texture"], ["uv", "model"], ["animation"], ["ogg", "sound"]],
                         "forbid": []},
        },
    ])
    return tests



def coder_tests_for(root: Path) -> list[dict]:
    mapping = mapping_evidence(root)
    if mapping.get("available"):
        mapping_prompt = (
            "Return JSON only with keys mapped_name, namespace, confidence. Use ONLY this mapping evidence: "
            f"Minecraft {mapping['version']}; {mapping['namespace_from']} name={mapping['name_from']!r}; "
            f"{mapping['namespace_to']} name={mapping['name_to']!r}. "
            f"Return the {mapping['namespace_to']} name for {mapping['name_from']!r}."
        )
        mapping_expected = {"contains": [mapping["name_to"], mapping["namespace_to"]], "forbid": []}
    else:
        mapping_prompt = (
            "Return JSON only with keys mapped_name, namespace, confidence. Evidence: Minecraft 1.12.2; "
            "SRG func_184185_a maps to MCP-readable collideWithNearbyEntities. Return the MCP-readable name."
        )
        mapping_expected = {"contains": ["collideWithNearbyEntities", "mcp"], "forbid": []}

    return [
        {"id":"mapping_grounded","weight":10,"prompt":mapping_prompt,"expected":mapping_expected},
        {"id":"java_compile_repair","weight":15,"prompt":(
            "Return JSON only with keys diagnosis, fixed_code, validation. Fix this Java compile error without changing behavior:\n"
            "public static int parseOrZero(String s) { try { return Integer.parseInt(s); } "
            "catch (NumberFormatException e) { return \"0\"; } }\n"
            "The method must return integer zero on NumberFormatException. Validation must mention compilation."
        ),"expected":{"contains":["return 0;","NumberFormatException"],"contains_any":["compile","compilation","javac"],"forbid":["return \"0\";"]}},
        {"id":"java_collection_repair","weight":15,"prompt":(
            "Return JSON only with keys diagnosis, fixed_code, validation. This Java code can throw ConcurrentModificationException:\n"
            "for (String s : names) { if (s.isBlank()) names.remove(s); }\n"
            "Repair it while preserving the intent: remove blank strings. Use removeIf or an Iterator and explain the failure mode concisely."
        ),"expected":{"contains":["ConcurrentModificationException"],"contains_any_groups":[["removeIf","Iterator"]],"forbid":[]}},
        {"id":"gradle_no_hallucination","weight":15,"prompt":(
            "Return JSON only with keys diagnosis, next_checks, invented_dependency. Gradle says only "
            "'Could not resolve all files for configuration'. No artifact coordinates or repository error are present. "
            "Do not invent a dependency; invented_dependency must be null. Ask for/inspect the exact unresolved artifact and detailed logs."
        ),"expected":{"contains":["invented_dependency"],"contains_any_groups":[["artifact","dependency"],["--info","--stacktrace","logs"]],"forbid":["geckolib","jei","examplemod"]}},
        {"id":"evidence_driven_neoforge_port","weight":15,"prompt":(
            "Return JSON only with keys plan, target_pattern, validation. You are porting ONE registry declaration. "
            "Use only this supplied target evidence: NeoForge target pattern is `DeferredRegister.Blocks BLOCKS = DeferredRegister.createBlocks(MODID);` "
            "and registration is `DeferredBlock<Block> ROCK = BLOCKS.registerSimpleBlock(\"rock\", BlockBehaviour.Properties.of());`. "
            "State that exact target pattern and make project compilation the primary validation. Do not introduce RegistryObject."
        ),"expected":{"contains":["DeferredRegister.Blocks","createBlocks","DeferredBlock","registerSimpleBlock"],"contains_any":["compile","compilation","gradle"],"forbid":["RegistryObject"]}},
        {"id":"api_guardrail","weight":10,"prompt":(
            "Return JSON only with keys answer, evidence_needed, confidence. Source is Forge 1.20.1 and target is NeoForge 26.2, "
            "but no target API documentation or source is provided. Do NOT invent exact replacement method/class names. "
            "State that target API evidence is required before editing and compilation is required before claiming success."
        ),"expected":{"contains_any_groups":[["evidence","documentation","source"],["compile","compilation"]],"forbid":["RegistryObject ->","replace RegistryObject with"]}},
        {"id":"code_review_bugs","weight":10,"prompt":(
            "Return JSON only with keys bugs, fixes, validation. Review this Java method and identify BOTH explicit defects:\n"
            "static int average(int[] values) { int total=0; for(int i=0;i<=values.length;i++) total+=values[i]; return total/values.length; }\n"
            "Required defects: loop bound reads past the array, and empty array causes division by zero. Give fixes for both."
        ),"expected":{"contains_any_groups":[["i < values.length","i<values.length","<=","out of bounds","ArrayIndexOutOfBounds"],["empty","zero","division by zero","length == 0","length==0"]],"forbid":[]}},
        {"id":"single_task_migration_scope","weight":10,"prompt":(
            "Return JSON only with keys task, evidence_needed, validation. Scope exactly ONE task: port one Forge 1.20.1 entity registration class to NeoForge 26.2. "
            "Require the source class and target API evidence; compilation is the primary validation. Do not expand into assets, networking, worldgen, or unrelated classes."
        ),"expected":{"contains":["evidence_needed","validation"],"contains_any":["compile","compilation","gradle"],"forbid":["networking","worldgen"]}},
    ]



def heavy_tests_for(root: Path) -> list[dict]:
    base = tests_for(root)
    return base + [
        {"id":"deep_java_repair","weight":20,"prompt":(
            "Return JSON only with keys diagnosis, fixed_code, validation. Repair this Java method while preserving semantics and identify both bugs: "
            "static int find(int[] a,int x){ for(int i=0;i<=a.length;i++){ if(a[i]==x)return i;} return -1;} "
            "Fix the loop bound and explicitly state compilation/testing validation."
        ),"expected":{"contains_any_groups":[["i < a.length","i<a.length","out of bounds","ArrayIndexOutOfBounds"],["compile","compilation","test"]],"forbid":[]}},
        {"id":"reviewer_precision","weight":20,"prompt":(
            "Return JSON only with keys defects, non_defects, validation. Review: `if (name == null || name.isBlank()) return;` "
            "Do not invent a bug in this guard clause. State that no defect is established from this line alone and that broader context/compilation is needed before changing code."
        ),"expected":{"contains_any":["no defect","not established","insufficient","context"],"contains_any_groups":[["compile","compilation","context"]],"forbid":["NullPointerException"]}},
        {"id":"evidence_first_api_repair","weight":20,"prompt":(
            "Return JSON only with keys action, evidence_needed, validation. A NeoForge 26.2 compile error says only `cannot find symbol` on an unknown method. "
            "No source declaration or API docs are provided. Do not invent a replacement API. Require the exact compiler line/source and target API evidence, then compilation."
        ),"expected":{"contains_any_groups":[["source","compiler","line"],["evidence","documentation","api"],["compile","compilation"]],"forbid":["RegistryObject","DeferredRegister.create"]}},
    ]


def reviewer_tests_for(root: Path) -> list[dict]:
    return [
        {"id":"false_positive_guard","weight":15,"prompt":(
            "Return JSON only with keys defects, non_defects, validation. Review only this line: `if (name == null || name.isBlank()) return;` "
            "Do not invent a defect. State that no defect is established from this line alone and that broader source context or compilation evidence is required before editing."
        ),"expected":{"contains_any":["no defect","not established","insufficient"],"contains_any_groups":[["context","compile","compilation"]],"forbid":["NullPointerException"]}},
        {"id":"reject_bad_fix","weight":15,"prompt":(
            "Return JSON only with keys verdict, reason, validation. A proposed fix changes `for (int i=0; i<a.length; i++)` to `for (int i=0; i<=a.length; i++)`. "
            "Reject the proposed fix, identify the out-of-bounds risk, and require compilation/tests."
        ),"expected":{"contains_any":["reject","incorrect","wrong"],"contains_any_groups":[["out of bounds","ArrayIndexOutOfBounds","<=a.length","<= a.length"],["compile","compilation","test"]]}},
        {"id":"evidence_first_neoforge_review","weight":15,"prompt":(
            "Return JSON only with keys verdict, evidence_needed, validation. A NeoForge 26.2 patch replaces an unknown missing method with `DeferredRegister.create(...)`, but no target API source or compiler line is supplied. "
            "Do not approve or invent the API. Require exact source/compiler evidence and target NeoForge API evidence, then compilation."
        ),"expected":{"contains_any_groups":[["source","compiler","line"],["api","documentation","evidence"],["compile","compilation"]],"forbid":["approved","looks correct"]}},
        {"id":"behavior_preservation","weight":15,"prompt":(
            "Return JSON only with keys risks, required_checks, verdict. Review a migration patch that compiles but removes an existing null guard and changes an entity registry id. "
            "Flag both behavior regressions; compilation alone is insufficient and runtime/registry behavior must be checked."
        ),"expected":{"contains_any_groups":[["null guard","null"],["registry id","registry","id"],["runtime","behavior"],["compile","compilation"]]}},
        {"id":"gradle_root_cause_discipline","weight":10,"prompt":(
            "Return JSON only with keys diagnosis, evidence_needed, verdict. The only error provided is `Could not resolve all files for configuration`. "
            "Do not name a missing dependency. Require the exact unresolved artifact/repository lines before diagnosing root cause."
        ),"expected":{"contains_any_groups":[["artifact","dependency"],["repository","repo","logs","line"]],"forbid":["jcenter"]}},
        {"id":"mapping_evidence_review","weight":10,"prompt":(
            "Return JSON only with keys verdict, evidence_needed, validation. A patch claims `b$1` maps to a target symbol but does not state source/target namespaces. "
            "Do not guess mapping direction. Require deterministic mapping evidence including Minecraft version and both namespaces."
        ),"expected":{"contains_any_groups":[["namespace","namespaces"],["version","minecraft"],["mapping","evidence"]],"forbid":[]}},
        {"id":"concurrent_modification_review","weight":10,"prompt":(
            "Return JSON only with keys defect, safe_fix, validation. Review `for (String s : names) { if (s.isBlank()) names.remove(s); }`. "
            "Identify ConcurrentModificationException risk, suggest iterator removal or removeIf, and require tests/compilation."
        ),"expected":{"contains_any_groups":[["ConcurrentModificationException","concurrent modification"],["iterator","removeIf"],["compile","compilation","test"]]}},
        {"id":"scope_control","weight":10,"prompt":(
            "Return JSON only with keys scope, reject, validation. The task is to fix one entity registration class. A proposed patch also rewrites networking, worldgen and textures. "
            "Reject unrelated changes and keep the repair constrained to the class plus strictly required references; compile first."
        ),"expected":{"contains_any":["reject","unrelated","scope"],"contains_any_groups":[["compile","compilation"]]}},
    ]

def request_json(url: str, payload: dict, timeout: int = 300) -> tuple[dict, float]:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r), time.perf_counter() - started
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body[:4000]}") from exc


def post(url: str, model: str, prompt: str, timeout: int = 300, max_tokens_override: int | None = None):
    max_tokens = max_tokens_override or TOKEN_LIMITS[model]
    request = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": max_tokens,
    }
    thinking = os.environ.get("GOKU_ENABLE_THINKING")
    if thinking is not None:
        normalized = thinking.strip().lower()
        if normalized not in {"true", "false", "1", "0", "yes", "no"}:
            raise ValueError("GOKU_ENABLE_THINKING must be true or false")
        request["chat_template_kwargs"] = {
            "enable_thinking": normalized in {"true", "1", "yes"}
        }
    data, elapsed = request_json(url, request, timeout=timeout)
    choice = data["choices"][0]
    text = choice["message"]["content"]
    finish_reason = choice.get("finish_reason")
    usage = data.get("usage", {})
    truncated = finish_reason == "length" or int(usage.get("completion_tokens", 0) or 0) >= max_tokens
    return text, elapsed, usage, finish_reason, truncated


def cleaned_json(text: str):
    s = text.strip()
    if s.startswith("```"):
        lines = s.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        s = "\n".join(lines).strip()
    try:
        return json.loads(s)
    except Exception:
        return None


def score_response(text: str, expected: dict, truncated: bool) -> dict:
    lower = text.lower()
    json_obj = cleaned_json(text)
    factual = 100.0
    reasons = []

    contains = expected.get("contains", [])
    if contains:
        hit = sum(1 for x in contains if str(x).lower() in lower)
        factual *= hit / len(contains)
        if hit != len(contains): reasons.append(f"missing required evidence token(s): {len(contains)-hit}")

    any_terms = expected.get("contains_any", [])
    if any_terms and not any(str(x).lower() in lower for x in any_terms):
        factual *= 0.35
        reasons.append("missing expected grounded conclusion")

    for group in expected.get("contains_any_groups", []):
        if not any(str(x).lower() in lower for x in group):
            factual *= 0.75
            reasons.append("missing required topic group: " + "/".join(group))

    forbidden = [x for x in expected.get("forbid", []) if str(x).lower() in lower]
    if forbidden:
        factual = 0.0
        reasons.append("unsupported/forbidden claim: " + ", ".join(forbidden))

    format_score = 100.0 if json_obj is not None else 0.0
    if truncated:
        factual *= 0.5
        reasons.append("response hit completion-token limit")

    # Benchmark v2 weights correctness over formatting. Speed is reported separately.
    quality = round(factual * 0.9 + format_score * 0.1, 2)
    return {"quality_score": quality, "factual_score": round(factual, 2),
            "format_score": format_score, "reasons": reasons}


def _read_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None


def _selected_label(selection: dict | None, fallback: str) -> str:
    if not isinstance(selection, dict):
        return fallback
    name = selection.get("name") or selection.get("id")
    if not name:
        return fallback
    quant = selection.get("quant")
    return f"{name} {quant}".strip() if quant else str(name)


def _routing_label(routing: dict | None, role: str, selection: dict | None, fallback: str) -> str:
    model = ((routing or {}).get("models") or {}).get(role) or {}
    name = model.get("model")
    quant = model.get("quant")
    opaque = (not name) or "selected" in str(name).lower() or str(name).endswith(".json")
    if opaque:
        return _selected_label(selection, fallback)
    label = str(name)
    if quant and str(quant) not in label:
        label = f"{label} {quant}"
    return label


def routing_recommendation(goku_root: Path) -> dict:
    models_dir = goku_root / "models"
    code = _read_json(models_dir / "code-selection.json")
    heavy = _read_json(models_dir / "heavy-selection.json")
    active = _read_json(models_dir / "active-worker.json")
    routing = _read_json(goku_root / "runtime" / "goku-routing.json")
    return {
        "goku-fast": _selected_label(code, "Qwen3-Coder-30B-A3B EXL3 4.0bpw"),
        "goku-code": _selected_label(code, "Qwen3-Coder-30B-A3B EXL3 4.0bpw"),
        "goku-heavy": _selected_label(heavy, "Qwen3.8-27B EXL3 3.5bpw"),
        "goku-research": _selected_label(heavy, "Qwen3.8-27B EXL3 3.5bpw"),
        "goku-reviewer": _selected_label(heavy, "Qwen3.8-27B EXL3 3.5bpw"),
        "active_worker": active,
        "note": (
            "GokuAI loads one EXL3 worker at a time via Switch-GokuWorker.ps1. "
            "Benchmark v2.2 reports grounded quality and latency; it does not auto-promote roles. "
            "Use Reset-GokuBackend.ps1 between workers so VRAM is flushed."
        ),
        "sources": {
            "goku_routing": str(goku_root / "runtime" / "goku-routing.json"),
            "code_selection": str(models_dir / "code-selection.json"),
            "heavy_selection": str(models_dir / "heavy-selection.json"),
            "active_worker": str(models_dir / "active-worker.json"),
            "proxy_url": ((routing or {}).get("proxy_url") if isinstance(routing, dict) else None),
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:11437/v1/chat/completions")
    ap.add_argument("--output", required=True)
    ap.add_argument("--root", default=r"C:\rmblocal_llm\knowledge",
                    help="Knowledge root for grounded mapping evidence (mappings corpus).")
    ap.add_argument("--goku-root", default=r"C:\gokuai",
                    help="GokuAI install root for routing/selection labels.")
    ap.add_argument("--models", nargs="*", choices=ALIASES, default=None)
    ap.add_argument("--suite", choices=["general", "coder", "heavy", "reviewer"], default="general")
    ap.add_argument("--report-as", default=None,
                    help="Optional report key override (e.g. goku-heavy-dflash while requesting alias goku-heavy).")
    ap.add_argument("--worker-label", default=None,
                    help="Optional human label recorded in the model block (e.g. heavy-dflash).")
    args = ap.parse_args()
    root = Path(args.root)
    goku_root = Path(args.goku_root)
    tests = (
        coder_tests_for(root) if args.suite == "coder"
        else heavy_tests_for(root) if args.suite == "heavy"
        else reviewer_tests_for(root) if args.suite == "reviewer"
        else tests_for(root)
    )

    report = {
        "schema": "rb-model-benchmark-v2.2",
        "product": "GokuAI",
        "created": datetime.datetime.now().isoformat(),
        "knowledge_root": str(root),
        "goku_root": str(goku_root),
        "scoring": "90% grounded/factual task criteria, 10% JSON format; latency reported separately and never auto-promotes roles",
        "suite": args.suite,
        "models": {},
        "policy": {
            "goku-fast": "mechanical/cheap work; same EXL3 pack as goku-code when fast worker loaded",
            "goku-code": "default fast coder / knowledge reader (Qwen3-Coder-30B-A3B EXL3)",
            "goku-heavy": "deep repair/reasoning (Qwen3.8-27B EXL3; MTP or DFlash2 draft)",
            "goku-research": "research/evidence/triage (currently aliases to heavy worker)",
            "goku-reviewer": "independent final reviewer (currently aliases to heavy worker)",
        },
    }

    selected_aliases = args.models or ["goku-code", "goku-heavy"]
    for alias in selected_aliases:
        report_key = args.report_as or alias
        rows = []
        print(f"[benchmark] {report_key} (alias={alias}): starting suite={args.suite}", flush=True)
        for test in tests:
            print(f"[benchmark] {report_key}: {test['id']}...", flush=True)
            try:
                if args.suite in ("heavy", "reviewer") and alias in ("goku-heavy", "goku-research", "goku-reviewer"):
                    token_limit = 1800
                elif args.suite == "coder" and alias in ("goku-fast", "goku-code"):
                    token_limit = 1000
                else:
                    token_limit = TOKEN_LIMITS[alias]
                text, elapsed, usage, finish_reason, truncated = post(
                    args.url, alias, test["prompt"], max_tokens_override=token_limit
                )
                scored = score_response(text, test["expected"], truncated)
                rows.append({
                    "test": test["id"], "weight": test["weight"], "ok": True,
                    "seconds": round(elapsed, 3), **scored, "usage": usage,
                    "finish_reason": finish_reason, "truncated": truncated,
                    "response": text[:5000],
                })
            except Exception as exc:
                rows.append({
                    "test": test["id"], "weight": test["weight"], "ok": False,
                    "quality_score": 0.0, "factual_score": 0.0, "format_score": 0.0,
                    "error": str(exc),
                })

        total_weight = sum(r["weight"] for r in rows)
        weighted = sum(r["quality_score"] * r["weight"] for r in rows) / total_weight if total_weight else 0
        successful_times = [r["seconds"] for r in rows if r.get("ok") and "seconds" in r]
        block = {
            "alias": alias,
            "worker_label": args.worker_label,
            "quality_score": round(weighted, 2),
            "success_rate": round(sum(1 for r in rows if r.get("ok")) * 100 / len(rows), 2),
            "mean_seconds": round(sum(successful_times) / len(successful_times), 3) if successful_times else None,
            "completion_limit": token_limit if rows else TOKEN_LIMITS[alias],
            "tests": rows,
        }
        report["models"][report_key] = block

    report["routing_recommendation"] = routing_recommendation(goku_root)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "report": str(out),
        "models": {k: {"quality": v["quality_score"], "success": v["success_rate"], "mean_s": v["mean_seconds"]}
                   for k, v in report["models"].items()},
    }, indent=2), flush=True)


if __name__ == "__main__":
    main()
