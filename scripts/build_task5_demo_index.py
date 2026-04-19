#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from task3_indexing import (  # noqa: E402
    DEFAULT_EMBEDDING_MODEL,
    FAISS_INDEX_DIRNAME,
    build_index_artifacts,
    cleanup_runtime_environment,
    create_embeddings,
    load_index,
    prepare_runtime_environment,
    search_index,
)


ATTACK_PREVIEW_QUERIES = (
    "swordfish",
    "root password",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a separate Task 5 demo index with a malicious document.")
    parser.add_argument(
        "--source-kb-dir",
        default="knowledge_base",
        help="Directory with the baseline synthetic KB.",
    )
    parser.add_argument(
        "--malicious-doc",
        default="Task5/malicious_document.md",
        help="Path to the malicious markdown document used for the injection demo.",
    )
    parser.add_argument(
        "--output-dir",
        default="artifacts/task5",
        help="Directory where Task 5 demo artifacts will be stored.",
    )
    parser.add_argument(
        "--model-name",
        default=DEFAULT_EMBEDDING_MODEL,
        help="Embedding model name.",
    )
    return parser.parse_args()


def rebuild_demo_kb(source_kb_dir: Path, malicious_doc: Path, demo_kb_dir: Path) -> None:
    if demo_kb_dir.exists():
        shutil.rmtree(demo_kb_dir)
    demo_kb_dir.mkdir(parents=True, exist_ok=True)

    for path in sorted(source_kb_dir.iterdir()):
        if path.is_file():
            shutil.copy2(path, demo_kb_dir / path.name)

    shutil.copy2(malicious_doc, demo_kb_dir / malicious_doc.name)


def preview_attack_queries(output_dir: Path, model_name: str) -> list[dict[str, object]]:
    runtime_dir = output_dir / "attack_preview_tmp"
    prepare_runtime_environment(runtime_dir)
    try:
        embeddings = create_embeddings(model_name)
        index = load_index(output_dir / FAISS_INDEX_DIRNAME, embeddings=embeddings)
        previews: list[dict[str, object]] = []
        for query in ATTACK_PREVIEW_QUERIES:
            previews.append(
                {
                    "query": query,
                    "matches": [match.__dict__ for match in search_index(index=index, query=query, top_k=3)],
                }
            )
        return previews
    finally:
        cleanup_runtime_environment(runtime_dir)


def main() -> int:
    args = parse_args()
    source_kb_dir = REPO_ROOT / args.source_kb_dir
    malicious_doc = REPO_ROOT / args.malicious_doc
    output_dir = REPO_ROOT / args.output_dir
    demo_kb_dir = output_dir / "demo_kb"

    rebuild_demo_kb(source_kb_dir=source_kb_dir, malicious_doc=malicious_doc, demo_kb_dir=demo_kb_dir)
    build_result = build_index_artifacts(
        knowledge_base_dir=demo_kb_dir,
        output_dir=output_dir,
        model_name=args.model_name,
        top_k_preview=3,
    )
    attack_preview = preview_attack_queries(output_dir=output_dir, model_name=args.model_name)
    attack_preview_path = output_dir / "attack_preview.json"
    attack_preview_path.write_text(json.dumps(attack_preview, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("Task 5 demo index build completed.")
    print(json.dumps(build_result.__dict__, indent=2, ensure_ascii=False))
    print(f"Demo KB directory: {demo_kb_dir}")
    print(f"Attack preview saved to: {attack_preview_path}")
    for preview in attack_preview:
        print(f"\nQuery: {preview['query']}")
        for match in preview["matches"]:
            print(
                f"  - rank={match['rank']} score={match['score']:.6f} "
                f"source={match['source_path']} section={match['section']} chunk={match['chunk_id']}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
