#!/usr/bin/env python3
"""Download GokuAI EXL3 weights into the station models folder."""
from __future__ import annotations

import argparse
import os
import sys

# Primary Mia stack + optional coder challenger for A/B.
DOWNLOADS = [
    {
        "key": "mia-target",
        "repo_id": "Mia-AiLab/Qwen3.8-27B-EXL3-3.5bpw",
        "dirname": "Qwen3.8-27B-EXL3-3.5bpw",
        "label": "Mia target (default worker)",
        "group": "primary",
    },
    {
        "key": "mia-draft",
        "repo_id": "Mia-AiLab/Qwen3.8-27B-DFlash2-EXL3-5.0bpw",
        "dirname": "Qwen3.8-27B-DFlash2-EXL3-5.0bpw",
        "label": "Mia DFlash2 draft (optional accelerator)",
        "group": "draft",
    },
    {
        "key": "coder-challenger",
        "repo_id": "AlexanderKyng/qwen3-coder-30b-a3b-instruct-exl3-4.0bpw-optimized",
        "dirname": "qwen3-coder-30b-a3b-instruct-exl3-4.0bpw-optimized",
        "label": "Qwen3-Coder-30B-A3B EXL3 4.0bpw challenger (~16GB)",
        "group": "challenger",
    },
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models-root", required=True)
    ap.add_argument("--skip-draft", action="store_true")
    ap.add_argument("--skip-challenger", action="store_true")
    ap.add_argument(
        "--only",
        choices=["primary", "draft", "challenger", "all"],
        default="all",
        help="Download subset only (default: all)",
    )
    args = ap.parse_args()

    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("huggingface_hub missing; install with: pip install huggingface_hub", file=sys.stderr)
        return 2

    models_root = os.path.abspath(args.models_root)
    os.makedirs(models_root, exist_ok=True)
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN") or None

    wanted = set()
    if args.only == "all":
        wanted = {"primary", "draft", "challenger"}
    else:
        wanted = {args.only}

    if args.skip_draft:
        wanted.discard("draft")
    if args.skip_challenger:
        wanted.discard("challenger")

    for item in DOWNLOADS:
        if item["group"] not in wanted:
            print(f"Skipping {item['key']} ({item['group']})", flush=True)
            continue
        local_dir = os.path.join(models_root, item["dirname"])
        print(f"Downloading {item['label']} -> {local_dir}", flush=True)
        snapshot_download(repo_id=item["repo_id"], local_dir=local_dir, token=token)
        print(f"Ready: {local_dir}", flush=True)

    print("EXL3 downloads complete", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
