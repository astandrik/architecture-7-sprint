#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from task3_indexing import (  # noqa: E402
    cleanup_runtime_environment,
    DEFAULT_EMBEDDING_MODEL,
    create_embeddings,
    load_index,
    prepare_runtime_environment,
    search_index,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Query the Task 3 FAISS index.")
    parser.add_argument(
        "--index-dir",
        default="artifacts/task3/faiss_index",
        help="Directory containing the saved FAISS index.",
    )
    parser.add_argument(
        "--query",
        required=True,
        help="Search query to run against the index.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=3,
        help="How many retrieval matches to return.",
    )
    parser.add_argument(
        "--model-name",
        default=DEFAULT_EMBEDDING_MODEL,
        help="Embedding model name used when the index was built.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    index_dir = REPO_ROOT / args.index_dir
    runtime_dir = index_dir.parent / "runtime_tmp"
    prepare_runtime_environment(runtime_dir)
    try:
        embeddings = create_embeddings(args.model_name)
        index = load_index(index_dir=index_dir, embeddings=embeddings)
        matches = search_index(index=index, query=args.query, top_k=args.top_k)

        print(f"Query: {args.query}")
        print(f"Top K: {args.top_k}")
        print("Scores are FAISS distances; lower is better.")
        for match in matches:
            print(
                f"\nRank {match.rank} | score={match.score:.6f} | "
                f"source={match.source_path} | section={match.section} | chunk={match.chunk_id}"
            )
            print(match.excerpt)

        return 0
    finally:
        cleanup_runtime_environment(runtime_dir)


if __name__ == "__main__":
    raise SystemExit(main())
