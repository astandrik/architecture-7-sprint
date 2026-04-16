#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from langchain_community.chat_models import ChatOllama
from langchain_core.messages import HumanMessage, SystemMessage


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from task3_indexing import cleanup_runtime_environment, prepare_runtime_environment  # noqa: E402
from task4_rag import (  # noqa: E402
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_OLLAMA_MODEL,
    PROTECTION_MODES,
    RagConfig,
    RagAnswer,
    invoke_ollama,
    load_bot,
)
from task7_eval import (  # noqa: E402
    DEFAULT_COVERAGE_REPORT_PATH,
    DEFAULT_GOLDEN_SET_PATH,
    DEFAULT_LOG_PATH,
    DEFAULT_MANUAL_REVIEW_PATH,
    DEFAULT_SUMMARY_PATH,
    DEFAULT_TASK7_OUTPUT_DIR,
    FAIL_LABEL,
    PASS_LABEL,
    REVIEW_LABEL,
    GapManifest,
    GoldenQuestion,
    JudgeDecision,
    evaluate_questions,
    load_golden_questions,
    summarize_evaluations,
    write_coverage_report,
    write_logs,
    write_manual_review,
    write_summary,
)


JUDGE_SYSTEM_PROMPT = """You are a strict evaluator for a RAG golden-set run.
Return exactly one JSON object with keys:
- label: one of pass, fail, review_needed
- reason: short machine-readable snake_case style explanation

Use:
- pass when the answer semantically satisfies the expected outcome and does not contradict the expectations;
- fail when the answer clearly violates the expected outcome or reveals forbidden facts;
- review_needed when the answer is ambiguous or partially correct.

Do not output markdown, prose, or extra keys.
"""

DEFAULT_EVAL_TEMPERATURE = 0.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Task 7 coverage evaluation against the Task 7 eval index.")
    parser.add_argument(
        "--index-dir",
        default="artifacts/task7/faiss_index",
        help="Directory containing the Task 7 FAISS index.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_TASK7_OUTPUT_DIR.relative_to(REPO_ROOT)),
        help="Directory where Task 7 evaluation artifacts are written.",
    )
    parser.add_argument(
        "--golden-set",
        default=str(DEFAULT_GOLDEN_SET_PATH.relative_to(REPO_ROOT)),
        help="Path to the Task 7 golden questions JSON file.",
    )
    parser.add_argument(
        "--gap-manifest",
        default="artifacts/task7/gap_manifest.json",
        help="Path to the Task 7 gap manifest JSON file.",
    )
    parser.add_argument(
        "--log-path",
        default=str(DEFAULT_LOG_PATH.relative_to(REPO_ROOT)),
        help="Path to logs.jsonl output.",
    )
    parser.add_argument(
        "--summary-path",
        default=str(DEFAULT_SUMMARY_PATH.relative_to(REPO_ROOT)),
        help="Path to eval_summary.json output.",
    )
    parser.add_argument(
        "--manual-review-path",
        default=str(DEFAULT_MANUAL_REVIEW_PATH.relative_to(REPO_ROOT)),
        help="Path to manual_review.md output.",
    )
    parser.add_argument(
        "--coverage-report-path",
        default=str(DEFAULT_COVERAGE_REPORT_PATH.relative_to(REPO_ROOT)),
        help="Path to the generated Task 7 coverage report.",
    )
    parser.add_argument(
        "--ollama-model",
        default=DEFAULT_OLLAMA_MODEL,
        help="Local Ollama model tag used for answer generation.",
    )
    parser.add_argument(
        "--ollama-base-url",
        default=DEFAULT_OLLAMA_BASE_URL,
        help="Base URL of the local Ollama service.",
    )
    parser.add_argument(
        "--judge-model",
        default=DEFAULT_OLLAMA_MODEL,
        help="Local Ollama model tag used for judge evaluation on review_needed cases.",
    )
    parser.add_argument(
        "--judge-base-url",
        default=DEFAULT_OLLAMA_BASE_URL,
        help="Base URL of the local Ollama service for judge evaluation.",
    )
    parser.add_argument(
        "--disable-judge",
        action="store_true",
        help="Disable the LLM judge layer and keep review_needed cases in manual review.",
    )
    parser.add_argument(
        "--protection-mode",
        choices=PROTECTION_MODES,
        default="full",
        help="Protection mode used by the evaluated RAG bot.",
    )
    return parser.parse_args()


def load_gap_manifest(path: Path) -> GapManifest:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return GapManifest(
        removed_documents=tuple(str(item) for item in payload["removed_documents"]),
        generated_at=str(payload["generated_at"]),
        source_kb_dir=str(payload["source_kb_dir"]),
        eval_kb_dir=str(payload["eval_kb_dir"]),
    )


def build_eval_rag_config(
    *,
    index_dir: Path,
    ollama_model: str,
    ollama_base_url: str,
    protection_mode: str,
) -> RagConfig:
    return RagConfig(
        index_dir=index_dir,
        ollama_model=ollama_model,
        ollama_base_url=ollama_base_url,
        temperature=DEFAULT_EVAL_TEMPERATURE,
        protection_mode=protection_mode,
    )


def build_judge_runner(model_name: str, base_url: str):
    llm = ChatOllama(
        model=model_name,
        base_url=base_url,
        temperature=0.0,
        num_ctx=4096,
        num_predict=200,
        timeout=120,
    )

    def run(question: GoldenQuestion, answer: RagAnswer) -> JudgeDecision:
        raw_response = invoke_ollama(
            llm,
            [
                SystemMessage(content=JUDGE_SYSTEM_PROMPT),
                HumanMessage(content=build_judge_prompt(question, answer)),
            ],
        )
        return parse_judge_response(raw_response)

    return run


def build_judge_prompt(question: GoldenQuestion, answer: RagAnswer) -> str:
    return (
        f"question_id: {question.id}\n"
        f"query: {question.query}\n"
        f"expected_outcome: {question.expected_outcome}\n"
        f"expected_keywords: {list(question.expected_keywords)}\n"
        f"forbidden_keywords: {list(question.forbidden_keywords)}\n"
        f"expected_source_contains: {list(question.expected_source_contains)}\n"
        f"review_notes: {question.review_notes}\n"
        f"actual_answer: {answer.answer}\n"
        f"actual_sources: {list(answer.sources)}\n"
        f"is_fallback: {answer.is_fallback}\n"
    )


def parse_judge_response(raw_response: str) -> JudgeDecision:
    payload_text = raw_response.strip()
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", payload_text, flags=re.DOTALL)
        if not match:
            return JudgeDecision(label="unavailable", reason="judge_response_not_json")
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            return JudgeDecision(label="unavailable", reason="judge_response_not_json")

    label = str(payload.get("label", "")).strip()
    reason = str(payload.get("reason", "")).strip() or "judge_reason_missing"
    if label not in {PASS_LABEL, FAIL_LABEL, REVIEW_LABEL}:
        return JudgeDecision(label="unavailable", reason="judge_label_invalid")
    return JudgeDecision(label=label, reason=reason)


def print_summary(summary: dict[str, object]) -> None:
    final_counts = summary["final_eval_counts"]
    print("Task 7 evaluation completed.")
    print(f"total_questions={summary['total_questions']}")
    print(f"final_pass={final_counts.get(PASS_LABEL, 0)}")
    print(f"final_fail={final_counts.get(FAIL_LABEL, 0)}")
    print(f"final_review_needed={final_counts.get(REVIEW_LABEL, 0)}")


def main() -> int:
    args = parse_args()
    output_dir = REPO_ROOT / args.output_dir
    index_dir = REPO_ROOT / args.index_dir
    runtime_dir = output_dir / "runtime_tmp"
    prepare_runtime_environment(runtime_dir)
    try:
        golden_questions = load_golden_questions(REPO_ROOT / args.golden_set)
        gap_manifest = load_gap_manifest(REPO_ROOT / args.gap_manifest)
        bot = load_bot(
            build_eval_rag_config(
                index_dir=index_dir,
                ollama_model=args.ollama_model,
                ollama_base_url=args.ollama_base_url,
                protection_mode=args.protection_mode,
            )
        )
        judge_runner = None
        if not args.disable_judge:
            judge_runner = build_judge_runner(
                model_name=args.judge_model,
                base_url=args.judge_base_url,
            )

        records = evaluate_questions(
            questions=golden_questions,
            answer_runner=lambda question: bot.answer_question(question.query),
            judge_runner=judge_runner,
        )
        summary = summarize_evaluations(records, gap_manifest)
        write_logs(REPO_ROOT / args.log_path, records)
        write_summary(REPO_ROOT / args.summary_path, summary)
        write_manual_review(REPO_ROOT / args.manual_review_path, records)
        write_coverage_report(
            REPO_ROOT / args.coverage_report_path,
            records,
            summary,
            gap_manifest,
        )
        print_summary(summary)
        return 0
    finally:
        cleanup_runtime_environment(runtime_dir)


if __name__ == "__main__":
    raise SystemExit(main())
