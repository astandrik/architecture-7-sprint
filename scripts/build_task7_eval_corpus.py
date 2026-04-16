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

from task7_eval import (  # noqa: E402
    DEFAULT_GAP_DOCUMENTS,
    DEFAULT_TASK7_OUTPUT_DIR,
    build_task7_eval_corpus,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the Task 7 evaluation corpus and FAISS index.")
    parser.add_argument(
        "--source-kb-dir",
        default="knowledge_base",
        help="Directory with the baseline synthetic KB.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_TASK7_OUTPUT_DIR.relative_to(REPO_ROOT)),
        help="Directory where Task 7 eval artifacts will be stored.",
    )
    parser.add_argument(
        "--gap-doc",
        action="append",
        dest="gap_docs",
        default=None,
        help="Markdown document to remove from the eval corpus. May be passed multiple times.",
    )
    parser.add_argument(
        "--model-name",
        default="sentence-transformers/all-MiniLM-L6-v2",
        help="Embedding model name used for the eval index.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    gap_docs = tuple(args.gap_docs) if args.gap_docs else DEFAULT_GAP_DOCUMENTS
    result = build_task7_eval_corpus(
        source_kb_dir=REPO_ROOT / args.source_kb_dir,
        output_dir=REPO_ROOT / args.output_dir,
        gap_documents=gap_docs,
        model_name=args.model_name,
    )

    print("Task 7 eval corpus build completed.")
    print(f"Eval KB directory: {result.eval_kb_dir}")
    print(f"Gap manifest: {result.gap_manifest_path}")
    print(json.dumps(asdict_safe(result.gap_manifest), indent=2, ensure_ascii=False))
    print(json.dumps(result.build_result.__dict__, indent=2, ensure_ascii=False))
    return 0


def asdict_safe(payload: object) -> dict[str, object]:
    if hasattr(payload, "__dict__"):
        return dict(payload.__dict__)
    raise TypeError("Unsupported payload type for JSON serialization.")


if __name__ == "__main__":
    raise SystemExit(main())
