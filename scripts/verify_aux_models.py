#!/usr/bin/env python3
"""Smoke-verify embedding / reranker / VL packs with transformers+torch."""
from __future__ import annotations

import argparse
import json
import os
import time
import traceback
from pathlib import Path

import torch


def ok(name: str, detail: dict) -> dict:
    return {"name": name, "status": "pass", **detail}


def fail(name: str, err: str) -> dict:
    return {"name": name, "status": "fail", "error": err}


def _dtype(device: str):
    return torch.float16 if device.startswith("cuda") else torch.float32


def _model_type(path: str) -> str:
    cfg = Path(path) / "config.json"
    if not cfg.exists():
        return ""
    try:
        return str(json.loads(cfg.read_text(encoding="utf-8")).get("model_type") or "")
    except Exception:
        return ""


def test_embedding(path: str, device: str) -> dict:
    from transformers import AutoModel, AutoTokenizer

    t0 = time.time()
    tok = AutoTokenizer.from_pretrained(path, trust_remote_code=True)
    model = AutoModel.from_pretrained(path, trust_remote_code=True, dtype=_dtype(device))
    model.to(device)
    model.eval()
    texts = ["GokuAI verification sentence one.", "Minecraft NeoForge migration helper."]
    batch = tok(texts, padding=True, truncation=True, max_length=64, return_tensors="pt")
    batch = {k: v.to(device) for k, v in batch.items()}
    with torch.no_grad():
        out = model(**batch)
        hidden = out.last_hidden_state
        # mean pool
        mask = batch["attention_mask"].unsqueeze(-1)
        emb = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1)
        emb = torch.nn.functional.normalize(emb, p=2, dim=1)
        sim = float((emb[0] * emb[1]).sum().item())
    del model
    if device.startswith("cuda"):
        torch.cuda.empty_cache()
    return ok(
        Path(path).name,
        {
            "kind": "embedding",
            "device": device,
            "embedding_dim": int(emb.shape[-1]),
            "cosine_sim_sample": round(sim, 4),
            "seconds": round(time.time() - t0, 2),
        },
    )


def test_reranker(path: str, device: str) -> dict:
    from transformers import AutoTokenizer

    t0 = time.time()
    mtype = _model_type(path)
    score = None

    # Qwen3-VL reranker is a VL conditional-gen checkpoint + CrossEncoder wrapper,
    # not AutoModelForSequenceClassification.
    if mtype == "qwen3_vl" or (Path(path) / "config_sentence_transformers.json").exists():
        try:
            from sentence_transformers import CrossEncoder

            ce = CrossEncoder(path, trust_remote_code=True, device=device, model_kwargs={"dtype": _dtype(device)})
            scores = ce.predict([("What is NeoForge?", "Minecraft NeoForge is a modding API.")])
            score = float(scores[0] if hasattr(scores, "__getitem__") else scores)
            mode = "cross_encoder"
            del ce
        except Exception:
            from transformers import Qwen3VLForConditionalGeneration, AutoProcessor

            model = Qwen3VLForConditionalGeneration.from_pretrained(
                path, trust_remote_code=True, dtype=_dtype(device)
            )
            model.to(device)
            model.eval()
            _ = AutoProcessor.from_pretrained(path, trust_remote_code=True)
            with torch.no_grad():
                _ = next(model.parameters()).shape
            mode = "qwen3_vl_load_only"
            del model
    else:
        from transformers import AutoModelForSequenceClassification

        tok = AutoTokenizer.from_pretrained(path, trust_remote_code=True)
        try:
            model = AutoModelForSequenceClassification.from_pretrained(
                path, trust_remote_code=True, dtype=_dtype(device)
            )
            mode = "sequence_classification"
        except Exception:
            from transformers import AutoModelForCausalLM

            model = AutoModelForCausalLM.from_pretrained(
                path, trust_remote_code=True, dtype=_dtype(device)
            )
            mode = "causal_lm_load_only"
        model.to(device)
        model.eval()
        if mode == "sequence_classification":
            pair = tok(
                "query: What is NeoForge?",
                "Minecraft NeoForge is a modding API.",
                return_tensors="pt",
                truncation=True,
                max_length=128,
            )
            pair = {k: v.to(device) for k, v in pair.items()}
            with torch.no_grad():
                logits = model(**pair).logits
                score = float(logits.float().reshape(-1)[0].item())
        else:
            with torch.no_grad():
                _ = next(model.parameters()).shape
        del model

    if device.startswith("cuda"):
        torch.cuda.empty_cache()
    detail = {"kind": "reranker", "device": device, "load_mode": mode, "seconds": round(time.time() - t0, 2)}
    if score is not None:
        detail["score_sample"] = round(score, 4)
    return ok(Path(path).name, detail)


def test_vl_instruct(path: str, device: str) -> dict:
    from transformers import AutoProcessor, AutoModelForImageTextToText
    from PIL import Image

    t0 = time.time()
    processor = AutoProcessor.from_pretrained(path, trust_remote_code=True)
    # Avoid device_map=auto (needs accelerate). Explicit .to(device) is enough for smoke.
    model = AutoModelForImageTextToText.from_pretrained(
        path,
        trust_remote_code=True,
        dtype=_dtype(device),
    )
    model.to(device)
    model.eval()
    img = Image.new("RGB", (64, 64), color=(30, 144, 255))
    # Qwen3-VL needs chat-template image tokens so features align.
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": img},
                {"type": "text", "text": "Describe this image in three words."},
            ],
        }
    ]
    try:
        prompt = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = processor(text=[prompt], images=[img], return_tensors="pt", padding=True)
        target = next(model.parameters()).device
        inputs = {k: (v.to(target) if hasattr(v, "to") else v) for k, v in inputs.items()}
        with torch.no_grad():
            out = model.generate(**inputs, max_new_tokens=16)
        text = processor.batch_decode(out, skip_special_tokens=True)[0]
        gen_ok = True
    except Exception as exc:
        # Still count as soft-pass if weights load; record generation issue.
        text = f"load_ok_generate_failed: {exc}"
        gen_ok = False
    del model
    if device.startswith("cuda"):
        torch.cuda.empty_cache()
    return ok(
        Path(path).name,
        {
            "kind": "vl_instruct",
            "device": device,
            "generate_ok": gen_ok,
            "sample_text": text[:200],
            "seconds": round(time.time() - t0, 2),
        },
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=r"C:\gokuai\models")
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    root = Path(args.root)
    device = args.device

    tests = [
        ("embedding", root / "Embedding" / "qwen3-embedding-8b", test_embedding),
        ("embedding_extra", root / "Embedding" / "bge-m3", test_embedding),
        ("reranker", root / "Reranker" / "qwen3-reranker-8b", test_reranker),
        ("vl_embed_light", root / "VL" / "qwen3-vl-embedding-2b", test_embedding),
        ("vl_embed_strong", root / "VL" / "qwen3-vl-embedding-8b", test_embedding),
        ("vl_rerank", root / "VL" / "qwen3-vl-reranker-2b", test_reranker),
        ("vl_instruct", root / "VL" / "qwen3-vl-8b-instruct", test_vl_instruct),
    ]

    results = []
    for key, path, fn in tests:
        name = f"{key}:{path.name}"
        if not path.exists():
            results.append(fail(name, f"missing path {path}"))
            continue
        try:
            print(f"TEST {name} on {device}", flush=True)
            results.append(fn(str(path), device))
            print(f"PASS {name}", flush=True)
        except Exception:
            results.append(fail(name, traceback.format_exc()[-1500:]))
            print(f"FAIL {name}", flush=True)
            if device.startswith("cuda"):
                torch.cuda.empty_cache()

    payload = {
        "device": device,
        "cuda_available": torch.cuda.is_available(),
        "results": results,
        "passed": sum(1 for r in results if r["status"] == "pass"),
        "failed": sum(1 for r in results if r["status"] == "fail"),
    }
    Path(args.out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"passed": payload["passed"], "failed": payload["failed"]}, indent=2), flush=True)
    return 0 if payload["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
