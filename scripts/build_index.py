#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from task3_indexing import (  # noqa: E402
    DEFAULT_EMBEDDING_MODEL,
    build_index_artifacts,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the Task 3 FAISS index for the synthetic KB.")
    parser.add_argument(
        "--kb-dir",
        default="knowledge_base",
        help="Directory with synthetic markdown documents.",
    )
    parser.add_argument(
        "--output-dir",
        default="artifacts/task3",
        help="Directory where Task 3 artifacts will be stored.",
    )
    parser.add_argument(
        "--model-name",
        default=DEFAULT_EMBEDDING_MODEL,
        help="Embedding model name.",
    )
    parser.add_argument(
        "--top-k-preview",
        type=int,
        default=3,
        help="How many retrieval matches to print for each preview query.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    knowledge_base_dir = REPO_ROOT / args.kb_dir
    output_dir = REPO_ROOT / args.output_dir

    build_result = build_index_artifacts(
        knowledge_base_dir=knowledge_base_dir,
        output_dir=output_dir,
        model_name=args.model_name,
        top_k_preview=args.top_k_preview,
    )

    print("Task 3 index build completed.")
    print(json.dumps(build_result.__dict__, indent=2, ensure_ascii=False))

    for preview in build_result.preview_queries:
        print(f"\nQuery: {preview['query']}")
        for match in preview["matches"]:
            print(
                f"  - rank={match['rank']} score={match['score']:.6f} "
                f"source={match['source_path']} section={match['section']} chunk={match['chunk_id']}"
            )
            print(f"    excerpt={match['excerpt']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
