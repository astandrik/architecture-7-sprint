#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from task4_rag import (  # noqa: E402
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_SCORE_THRESHOLD,
    DEFAULT_TOP_K,
    RagConfig,
    Task4RagError,
    format_rag_answer,
    load_bot,
)
from task3_indexing import cleanup_runtime_environment, prepare_runtime_environment  # noqa: E402


EXIT_COMMANDS = {"exit", "quit"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Task 4 REPL RAG bot over the local FAISS index.")
    parser.add_argument(
        "--index-dir",
        default="artifacts/task3/faiss_index",
        help="Directory containing the saved FAISS index.",
    )
    parser.add_argument(
        "--ollama-model",
        default=DEFAULT_OLLAMA_MODEL,
        help="Local Ollama model tag used for grounded answer generation.",
    )
    parser.add_argument(
        "--ollama-base-url",
        default=DEFAULT_OLLAMA_BASE_URL,
        help="Base URL of the local Ollama service.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=DEFAULT_TOP_K,
        help="How many nearest chunks to retrieve before relevance filtering.",
    )
    parser.add_argument(
        "--score-threshold",
        type=float,
        default=DEFAULT_SCORE_THRESHOLD,
        help="Maximum FAISS distance allowed for relevant chunks.",
    )
    parser.add_argument(
        "--query",
        help="Optional one-shot query. If omitted, the script starts the interactive REPL.",
    )
    return parser.parse_args()


def build_config(args: argparse.Namespace) -> RagConfig:
    return RagConfig(
        index_dir=REPO_ROOT / args.index_dir,
        ollama_model=args.ollama_model,
        ollama_base_url=args.ollama_base_url,
        top_k=args.top_k,
        score_threshold=args.score_threshold,
    )


def run_one_shot_query(bot, query: str) -> int:
    rag_answer = bot.answer_question(query)
    print(format_rag_answer(rag_answer))
    return 0


def run_repl_loop(bot) -> int:
    print("Task 4 REPL is ready. Type a question or `exit` to stop.")
    while True:
        try:
            query = input("rag> ").strip()
        except EOFError:
            print()
            return 0
        except KeyboardInterrupt:
            print()
            return 0

        if not query:
            continue
        if query.lower() in EXIT_COMMANDS:
            return 0

        rag_answer = bot.answer_question(query)
        print(format_rag_answer(rag_answer))
        print()


def main() -> int:
    args = parse_args()
    config = build_config(args)
    runtime_dir = config.index_dir.parent / "runtime_tmp"
    try:
        prepare_runtime_environment(runtime_dir)
        bot = load_bot(config)
        if args.query:
            return run_one_shot_query(bot, args.query)
        return run_repl_loop(bot)
    except (Task4RagError, ValueError) as error:
        print(f"Task 4 REPL failed: {error}", file=sys.stderr)
        return 1
    finally:
        cleanup_runtime_environment(runtime_dir)


if __name__ == "__main__":
    raise SystemExit(main())
