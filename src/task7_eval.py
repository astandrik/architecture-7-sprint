from __future__ import annotations

import json
import re
import shutil
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from task3_indexing import DEFAULT_EMBEDDING_MODEL, BuildResult, build_index_artifacts
from task4_rag import RagAnswer


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TASK7_OUTPUT_DIR = REPO_ROOT / "artifacts" / "task7"
DEFAULT_GAP_DOCUMENTS = ("elyra-noctis.md", "the-hollow-eclipse.md", "skyball.md")
DEFAULT_GOLDEN_SET_PATH = REPO_ROOT / "Task7" / "golden_questions.json"
DEFAULT_LOG_PATH = DEFAULT_TASK7_OUTPUT_DIR / "logs.jsonl"
DEFAULT_SUMMARY_PATH = DEFAULT_TASK7_OUTPUT_DIR / "eval_summary.json"
DEFAULT_MANUAL_REVIEW_PATH = DEFAULT_TASK7_OUTPUT_DIR / "manual_review.md"
DEFAULT_COVERAGE_REPORT_PATH = REPO_ROOT / "Task7" / "task_7_coverage.md"
PASS_LABEL = "pass"
FAIL_LABEL = "fail"
REVIEW_LABEL = "review_needed"
UNAVAILABLE_LABEL = "unavailable"
ANSWER_OUTCOME = "answer"
FALLBACK_OUTCOME = "fallback"
EvaluationLabel = Literal["pass", "fail", "review_needed"]
JudgeLabel = Literal["pass", "fail", "review_needed", "unavailable"]
OutcomeLabel = Literal["answer", "fallback"]
BuildIndexFn = Callable[..., BuildResult]
JudgeRunner = Callable[["GoldenQuestion", RagAnswer], "JudgeDecision"]
FALLBACK_LIKE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bя не знаю\b", re.IGNORECASE),
    re.compile(r"\bi don't know\b", re.IGNORECASE),
    re.compile(r"\bнет(?:\s+достаточной)?\s+информац", re.IGNORECASE),
    re.compile(r"\bинформац[а-я]*\b.*\bнет\b", re.IGNORECASE),
    re.compile(r"\bno (?:relevant|enough )?information\b", re.IGNORECASE),
    re.compile(r"\bthere is no information\b", re.IGNORECASE),
    re.compile(r"\bnot enough information\b", re.IGNORECASE),
)


@dataclass(frozen=True)
class GoldenQuestion:
    id: str
    query: str
    expected_outcome: OutcomeLabel
    expected_answer: str
    expected_keywords: tuple[str, ...]
    forbidden_keywords: tuple[str, ...]
    expected_source_contains: tuple[str, ...]
    review_notes: str


@dataclass(frozen=True)
class GapManifest:
    removed_documents: tuple[str, ...]
    generated_at: str
    source_kb_dir: str
    eval_kb_dir: str


@dataclass(frozen=True)
class Task7CorpusBuildResult:
    eval_kb_dir: Path
    gap_manifest_path: Path
    build_result: BuildResult
    gap_manifest: GapManifest


@dataclass(frozen=True)
class RuleEvaluation:
    label: EvaluationLabel
    reason: str
    missing_expected_keywords: tuple[str, ...]
    present_forbidden_keywords: tuple[str, ...]
    missing_expected_sources: tuple[str, ...]


@dataclass(frozen=True)
class JudgeDecision:
    label: JudgeLabel
    reason: str


@dataclass(frozen=True)
class EvaluationRecord:
    question_id: str
    query: str
    timestamp: str
    expected_outcome: OutcomeLabel
    actual_outcome: OutcomeLabel
    found_chunks: bool
    answer_length: int
    sources: tuple[str, ...]
    status: EvaluationLabel
    is_fallback: bool
    retrieved_hit_count: int
    top_source: str | None
    rule_eval: EvaluationLabel
    judge_eval: JudgeLabel
    final_eval: EvaluationLabel
    review_reason: str
    answer: str
    review_notes: str
    missing_expected_keywords: tuple[str, ...]
    present_forbidden_keywords: tuple[str, ...]
    missing_expected_sources: tuple[str, ...]

    def to_log_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "query": self.query,
            "timestamp": self.timestamp,
            "found_chunks": self.found_chunks,
            "answer_length": self.answer_length,
            "sources": list(self.sources),
            "status": self.status,
            "expected_outcome": self.expected_outcome,
            "actual_outcome": self.actual_outcome,
            "is_fallback": self.is_fallback,
            "retrieved_hit_count": self.retrieved_hit_count,
            "top_source": self.top_source,
            "rule_eval": self.rule_eval,
            "judge_eval": self.judge_eval,
            "final_eval": self.final_eval,
            "review_reason": self.review_reason,
            "answer": self.answer,
            "review_notes": self.review_notes,
            "missing_expected_keywords": list(self.missing_expected_keywords),
            "present_forbidden_keywords": list(self.present_forbidden_keywords),
            "missing_expected_sources": list(self.missing_expected_sources),
        }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def to_repo_relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def load_golden_questions(path: Path = DEFAULT_GOLDEN_SET_PATH) -> list[GoldenQuestion]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    questions: list[GoldenQuestion] = []
    for item in payload:
        questions.append(
            GoldenQuestion(
                id=str(item["id"]),
                query=str(item["query"]),
                expected_outcome=str(item["expected_outcome"]),
                expected_answer=str(item["expected_answer"]),
                expected_keywords=tuple(str(keyword) for keyword in item["expected_keywords"]),
                forbidden_keywords=tuple(str(keyword) for keyword in item["forbidden_keywords"]),
                expected_source_contains=tuple(str(source) for source in item["expected_source_contains"]),
                review_notes=str(item["review_notes"]),
            )
        )
    return questions


def build_task7_eval_corpus(
    source_kb_dir: Path,
    output_dir: Path = DEFAULT_TASK7_OUTPUT_DIR,
    gap_documents: tuple[str, ...] = DEFAULT_GAP_DOCUMENTS,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    build_index_fn: BuildIndexFn = build_index_artifacts,
) -> Task7CorpusBuildResult:
    if not source_kb_dir.exists():
        raise FileNotFoundError(f"Source KB directory does not exist: {source_kb_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    eval_kb_dir = output_dir / "eval_kb"
    if eval_kb_dir.exists():
        shutil.rmtree(eval_kb_dir)
    eval_kb_dir.mkdir(parents=True, exist_ok=True)

    for path in sorted(source_kb_dir.iterdir()):
        if path.is_file():
            shutil.copy2(path, eval_kb_dir / path.name)

    removed_documents: list[str] = []
    for filename in gap_documents:
        candidate = eval_kb_dir / filename
        if not candidate.exists():
            raise FileNotFoundError(f"Gap document does not exist in eval corpus: {filename}")
        candidate.unlink()
        removed_documents.append(filename)

    gap_manifest = GapManifest(
        removed_documents=tuple(removed_documents),
        generated_at=utc_now_iso(),
        source_kb_dir=to_repo_relative_path(source_kb_dir),
        eval_kb_dir=to_repo_relative_path(eval_kb_dir),
    )
    gap_manifest_path = output_dir / "gap_manifest.json"
    gap_manifest_path.write_text(json.dumps(asdict(gap_manifest), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    build_result = build_index_fn(
        knowledge_base_dir=eval_kb_dir,
        output_dir=output_dir,
        model_name=model_name,
        top_k_preview=3,
    )
    return Task7CorpusBuildResult(
        eval_kb_dir=eval_kb_dir,
        gap_manifest_path=gap_manifest_path,
        build_result=build_result,
        gap_manifest=gap_manifest,
    )


def normalize_text(value: str) -> str:
    return " ".join(value.casefold().split())


def looks_like_fallback(answer_text: str) -> bool:
    normalized_answer = answer_text.strip()
    return any(pattern.search(normalized_answer) for pattern in FALLBACK_LIKE_PATTERNS)


def compute_actual_outcome(answer: RagAnswer) -> OutcomeLabel:
    if answer.is_fallback or looks_like_fallback(answer.answer):
        return FALLBACK_OUTCOME
    return ANSWER_OUTCOME


def classify_rule_evaluation(question: GoldenQuestion, answer: RagAnswer) -> RuleEvaluation:
    actual_outcome = compute_actual_outcome(answer)
    normalized_answer = normalize_text(answer.answer)
    normalized_sources = tuple(normalize_text(source) for source in answer.sources)
    missing_expected_keywords = tuple(
        keyword for keyword in question.expected_keywords if normalize_text(keyword) not in normalized_answer
    )
    present_forbidden_keywords = tuple(
        keyword for keyword in question.forbidden_keywords if normalize_text(keyword) in normalized_answer
    )
    missing_expected_sources = tuple(
        source_fragment
        for source_fragment in question.expected_source_contains
        if not any(normalize_text(source_fragment) in source for source in normalized_sources)
    )

    if question.expected_outcome == ANSWER_OUTCOME:
        if actual_outcome == FALLBACK_OUTCOME:
            return RuleEvaluation(
                label=FAIL_LABEL,
                reason="expected_grounded_answer_got_fallback",
                missing_expected_keywords=missing_expected_keywords,
                present_forbidden_keywords=present_forbidden_keywords,
                missing_expected_sources=missing_expected_sources,
            )
        if present_forbidden_keywords:
            return RuleEvaluation(
                label=FAIL_LABEL,
                reason="positive_answer_contains_forbidden_keywords",
                missing_expected_keywords=missing_expected_keywords,
                present_forbidden_keywords=present_forbidden_keywords,
                missing_expected_sources=missing_expected_sources,
            )
        if not missing_expected_keywords and not missing_expected_sources:
            return RuleEvaluation(
                label=PASS_LABEL,
                reason="positive_answer_matches_expected_keywords_and_sources",
                missing_expected_keywords=(),
                present_forbidden_keywords=(),
                missing_expected_sources=(),
            )

        matched_keyword_count = len(question.expected_keywords) - len(missing_expected_keywords)
        matched_source_count = len(question.expected_source_contains) - len(missing_expected_sources)
        if matched_keyword_count > 0 or matched_source_count > 0:
            return RuleEvaluation(
                label=REVIEW_LABEL,
                reason="positive_answer_partially_matches_expected_evidence",
                missing_expected_keywords=missing_expected_keywords,
                present_forbidden_keywords=present_forbidden_keywords,
                missing_expected_sources=missing_expected_sources,
            )
        return RuleEvaluation(
            label=FAIL_LABEL,
            reason="positive_answer_missing_expected_evidence",
            missing_expected_keywords=missing_expected_keywords,
            present_forbidden_keywords=present_forbidden_keywords,
            missing_expected_sources=missing_expected_sources,
        )

    if actual_outcome != FALLBACK_OUTCOME:
        return RuleEvaluation(
            label=FAIL_LABEL,
            reason="expected_fallback_got_grounded_answer",
            missing_expected_keywords=missing_expected_keywords,
            present_forbidden_keywords=present_forbidden_keywords,
            missing_expected_sources=missing_expected_sources,
        )
    if present_forbidden_keywords:
        return RuleEvaluation(
            label=FAIL_LABEL,
            reason="fallback_answer_contains_gap_facts",
            missing_expected_keywords=missing_expected_keywords,
            present_forbidden_keywords=present_forbidden_keywords,
            missing_expected_sources=missing_expected_sources,
        )
    return RuleEvaluation(
        label=PASS_LABEL,
        reason="fallback_answer_correctly_withholds_gap_information",
        missing_expected_keywords=(),
        present_forbidden_keywords=(),
        missing_expected_sources=(),
    )


def evaluate_question(
    question: GoldenQuestion,
    answer: RagAnswer,
    judge_runner: JudgeRunner | None = None,
    timestamp: str | None = None,
) -> EvaluationRecord:
    rule_evaluation = classify_rule_evaluation(question, answer)
    judge_label: JudgeLabel = UNAVAILABLE_LABEL
    final_eval: EvaluationLabel = rule_evaluation.label
    review_reasons = [rule_evaluation.reason]

    if rule_evaluation.label == REVIEW_LABEL:
        if judge_runner is None:
            review_reasons.append("judge_unavailable_for_review_needed_case")
        else:
            try:
                judge_decision = judge_runner(question, answer)
            except Exception as error:  # pragma: no cover - defensive path
                judge_decision = JudgeDecision(label=UNAVAILABLE_LABEL, reason=f"judge_runner_failed: {error}")
            judge_label = judge_decision.label
            review_reasons.append(judge_decision.reason)
            if judge_decision.label in {PASS_LABEL, FAIL_LABEL}:
                final_eval = judge_decision.label
            else:
                final_eval = REVIEW_LABEL

    actual_outcome = compute_actual_outcome(answer)
    sources = tuple(answer.sources)
    top_source = sources[0] if sources else None
    final_reason = "; ".join(reason for reason in review_reasons if reason)

    return EvaluationRecord(
        question_id=question.id,
        query=question.query,
        timestamp=timestamp or utc_now_iso(),
        expected_outcome=question.expected_outcome,
        actual_outcome=actual_outcome,
        found_chunks=bool(answer.retrieved_hits),
        answer_length=len(answer.answer),
        sources=sources,
        status=final_eval,
        is_fallback=answer.is_fallback,
        retrieved_hit_count=len(answer.retrieved_hits),
        top_source=top_source,
        rule_eval=rule_evaluation.label,
        judge_eval=judge_label,
        final_eval=final_eval,
        review_reason=final_reason,
        answer=answer.answer,
        review_notes=question.review_notes,
        missing_expected_keywords=rule_evaluation.missing_expected_keywords,
        present_forbidden_keywords=rule_evaluation.present_forbidden_keywords,
        missing_expected_sources=rule_evaluation.missing_expected_sources,
    )


def evaluate_questions(
    questions: list[GoldenQuestion],
    answer_runner: Callable[[GoldenQuestion], RagAnswer],
    judge_runner: JudgeRunner | None = None,
) -> list[EvaluationRecord]:
    records: list[EvaluationRecord] = []
    for question in questions:
        answer = answer_runner(question)
        records.append(
            evaluate_question(
                question=question,
                answer=answer,
                judge_runner=judge_runner,
            )
        )
    return records


def write_logs(path: Path, records: list[EvaluationRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(json.dumps(record.to_log_dict(), ensure_ascii=False) for record in records)
    path.write_text(payload + "\n", encoding="utf-8")


def summarize_evaluations(records: list[EvaluationRecord], gap_manifest: GapManifest) -> dict[str, Any]:
    rule_counts = Counter(record.rule_eval for record in records)
    judge_counts = Counter(
        record.judge_eval for record in records if record.rule_eval == REVIEW_LABEL
    )
    final_counts = Counter(record.final_eval for record in records)
    positive_records = [record for record in records if record.expected_outcome == ANSWER_OUTCOME]
    negative_records = [record for record in records if record.expected_outcome == FALLBACK_OUTCOME]
    well_covered_topics = [
        {"id": record.question_id, "query": record.query}
        for record in positive_records
        if record.final_eval == PASS_LABEL
    ]
    uncovered_gap_cases = [
        {
            "id": record.question_id,
            "query": record.query,
            "final_eval": record.final_eval,
            "reason": record.review_reason,
        }
        for record in negative_records
    ]
    poor_coverage_topics = [
        {
            "id": record.question_id,
            "query": record.query,
            "final_eval": record.final_eval,
            "reason": record.review_reason,
        }
        for record in records
        if record.final_eval != PASS_LABEL
    ]
    irrelevant_source_cases = [
        {
            "id": record.question_id,
            "query": record.query,
            "top_source": record.top_source,
            "missing_expected_sources": list(record.missing_expected_sources),
        }
        for record in records
        if record.missing_expected_sources and record.actual_outcome == ANSWER_OUTCOME
    ]
    manual_review_cases = [
        {"id": record.question_id, "query": record.query, "reason": record.review_reason}
        for record in records
        if record.final_eval == REVIEW_LABEL
    ]

    return {
        "generated_at": utc_now_iso(),
        "removed_documents": list(gap_manifest.removed_documents),
        "total_questions": len(records),
        "rule_eval_counts": dict(rule_counts),
        "judge_eval_counts": dict(judge_counts),
        "final_eval_counts": dict(final_counts),
        "positive_questions_total": len(positive_records),
        "negative_questions_total": len(negative_records),
        "well_covered_topics": well_covered_topics,
        "uncovered_gap_cases": uncovered_gap_cases,
        "poor_coverage_topics": poor_coverage_topics,
        "irrelevant_source_cases": irrelevant_source_cases,
        "manual_review_cases": manual_review_cases,
    }


def write_summary(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def render_manual_review_md(records: list[EvaluationRecord]) -> str:
    review_records = [record for record in records if record.final_eval == REVIEW_LABEL]
    lines = ["# Task 7 Manual Review Queue", ""]
    if not review_records:
        lines.extend(["No unresolved review cases.", ""])
        return "\n".join(lines)

    for record in review_records:
        lines.extend(
            [
                f"## {record.question_id}",
                "",
                f"- query: `{record.query}`",
                f"- expected_outcome: `{record.expected_outcome}`",
                f"- actual_outcome: `{record.actual_outcome}`",
                f"- rule_eval: `{record.rule_eval}`",
                f"- judge_eval: `{record.judge_eval}`",
                f"- final_eval: `{record.final_eval}`",
                f"- review_reason: `{record.review_reason}`",
                f"- sources: {', '.join(record.sources) if record.sources else 'none'}",
                f"- missing_expected_keywords: {', '.join(record.missing_expected_keywords) if record.missing_expected_keywords else 'none'}",
                f"- missing_expected_sources: {', '.join(record.missing_expected_sources) if record.missing_expected_sources else 'none'}",
                "",
                "Answer:",
                "",
                "```text",
                record.answer,
                "```",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def write_manual_review(path: Path, records: list[EvaluationRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_manual_review_md(records), encoding="utf-8")


def render_coverage_report(
    records: list[EvaluationRecord],
    summary: dict[str, Any],
    gap_manifest: GapManifest,
) -> str:
    final_counts = summary["final_eval_counts"]
    positive_passes = [
        record for record in records if record.expected_outcome == ANSWER_OUTCOME and record.final_eval == PASS_LABEL
    ]
    negative_passes = [
        record for record in records if record.expected_outcome == FALLBACK_OUTCOME and record.final_eval == PASS_LABEL
    ]
    unresolved = [record for record in records if record.final_eval == REVIEW_LABEL]
    failed = [record for record in records if record.final_eval == FAIL_LABEL]
    irrelevant_sources = [
        record for record in records if record.missing_expected_sources and record.actual_outcome == ANSWER_OUTCOME
    ]

    recommendation_lines = [
        "- Вернуть в рабочую KB документы по Elyra Noctis, The Hollow Eclipse и Skyball, если эти темы считаются обязательными для production-покрытия.",
        "- Добавить явные golden-вопросы на соседние документы, где знания сейчас хранятся фрагментарно и retrieval легко уходит в косвенные источники.",
        "- Если positive-кейсы продолжают уходить в review или fail из-за источников, ужесточить критерии выбора top-k или расширить фактическое описание в оставшихся документах.",
    ]

    lines = [
        "# Task 7 Coverage Report",
        "",
        "## Summary",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- removed_documents: `{', '.join(gap_manifest.removed_documents)}`",
        f"- total_questions: `{summary['total_questions']}`",
        f"- final_pass: `{final_counts.get(PASS_LABEL, 0)}`",
        f"- final_fail: `{final_counts.get(FAIL_LABEL, 0)}`",
        f"- final_review_needed: `{final_counts.get(REVIEW_LABEL, 0)}`",
        "",
        "## Well-covered topics",
        "",
    ]
    if positive_passes:
        for record in positive_passes:
            lines.append(f"- `{record.query}`")
    else:
        lines.append("- No positive topics passed cleanly.")

    lines.extend(["", "## Gap findings", ""])
    if negative_passes:
        for record in negative_passes:
            lines.append(f"- `{record.query}` correctly fell back after removing the supporting document.")
    else:
        lines.append("- No gap-oriented question was cleanly surfaced as a missing-knowledge case.")

    lines.extend(["", "## Poorly covered topics", ""])
    if failed or unresolved:
        for record in failed + unresolved:
            lines.append(f"- `{record.query}` -> `{record.final_eval}` ({record.review_reason})")
    else:
        lines.append("- No poorly covered topics detected in the current golden set.")

    lines.extend(["", "## Irrelevant or weak sources", ""])
    if irrelevant_sources:
        for record in irrelevant_sources:
            lines.append(
                f"- `{record.query}` -> top_source `{record.top_source or 'none'}`; missing expected sources: "
                f"`{', '.join(record.missing_expected_sources)}`"
            )
    else:
        lines.append("- No obvious source-mismatch cases detected for grounded answers.")

    lines.extend(["", "## Recommendations", ""])
    lines.extend(recommendation_lines)
    lines.append("")
    return "\n".join(lines)


def write_coverage_report(
    path: Path,
    records: list[EvaluationRecord],
    summary: dict[str, Any],
    gap_manifest: GapManifest,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_coverage_report(records, summary, gap_manifest), encoding="utf-8")
