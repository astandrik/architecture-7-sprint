from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from task3_indexing import BuildResult  # noqa: E402
from task4_rag import ProtectionTrace, RagAnswer, RetrievedHit  # noqa: E402
from task7_eval import (  # noqa: E402
    FAIL_LABEL,
    PASS_LABEL,
    REVIEW_LABEL,
    GoldenQuestion,
    JudgeDecision,
    build_task7_eval_corpus,
    evaluate_question,
    load_golden_questions,
    render_manual_review_md,
)

EVALUATE_TASK7_SCRIPT_PATH = REPO_ROOT / "scripts" / "evaluate_task7.py"
EVALUATE_TASK7_SPEC = importlib.util.spec_from_file_location("evaluate_task7_script", EVALUATE_TASK7_SCRIPT_PATH)
assert EVALUATE_TASK7_SPEC is not None and EVALUATE_TASK7_SPEC.loader is not None
evaluate_task7_script = importlib.util.module_from_spec(EVALUATE_TASK7_SPEC)
EVALUATE_TASK7_SPEC.loader.exec_module(evaluate_task7_script)


def write_markdown(path: Path, title: str) -> None:
    path.write_text(
        (
            f"# {title}\n\n"
            "Type: document\n\n"
            "## Overview\n\n"
            f"{title} overview.\n\n"
            "## Details\n\n"
            f"{title} details.\n\n"
            "## Related entities\n\n"
            "- Related Entity\n"
        ),
        encoding="utf-8",
    )


def make_build_result(knowledge_base_dir: Path) -> BuildResult:
    return BuildResult(
        embedding_model="sentence-transformers/all-MiniLM-L6-v2",
        embedding_model_url="https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2",
        embedding_dimension=384,
        knowledge_base_dir=knowledge_base_dir.as_posix(),
        documents_count=1,
        chunks_count=2,
        chunking_strategy="stub",
        chunk_size=220,
        chunk_overlap=40,
        build_seconds=0.123,
        created_at="2026-04-15T00:00:00+00:00",
        preview_queries=[],
    )


def make_hit(source_path: str = "knowledge_base/caelan-veyr.md", title: str = "Caelan Veyr") -> RetrievedHit:
    return RetrievedHit(
        rank=1,
        score=0.5,
        chunk_id="chunk-001",
        source_path=source_path,
        title=title,
        section="Details",
        text="stub hit",
    )


def make_trace() -> ProtectionTrace:
    return ProtectionTrace(
        mode="full",
        preprompt_enabled=True,
        sanitize_enabled=True,
        postfilter_enabled=True,
        hit_traces=(),
    )


def make_answer(
    *,
    question: str,
    answer_text: str,
    sources: list[str],
    is_fallback: bool,
    retrieved_hits: list[RetrievedHit] | None = None,
) -> RagAnswer:
    return RagAnswer(
        question=question,
        steps=["stub step"],
        answer=answer_text,
        sources=sources,
        is_fallback=is_fallback,
        retrieved_hits=retrieved_hits or [make_hit()],
        raw_response="raw",
        protection_trace=make_trace(),
    )


class Task7EvaluateTests(unittest.TestCase):
    def test_build_eval_rag_config_uses_deterministic_temperature(self) -> None:
        config = evaluate_task7_script.build_eval_rag_config(
            index_dir=Path("artifacts/task7/faiss_index"),
            ollama_model="qwen2.5:7b-instruct",
            ollama_base_url="http://localhost:11434",
            protection_mode="full",
        )

        self.assertEqual(evaluate_task7_script.DEFAULT_EVAL_TEMPERATURE, 0.0)
        self.assertEqual(config.temperature, 0.0)

    def test_build_task7_eval_corpus_copies_baseline_and_removes_only_gap_docs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_kb_dir = root / "knowledge_base"
            output_dir = root / "artifacts" / "task7"
            source_kb_dir.mkdir(parents=True, exist_ok=True)
            write_markdown(source_kb_dir / "elyra-noctis.md", "Elyra Noctis")
            write_markdown(source_kb_dir / "the-hollow-eclipse.md", "The Hollow Eclipse")
            write_markdown(source_kb_dir / "skyball.md", "Skyball")
            write_markdown(source_kb_dir / "caelan-veyr.md", "Caelan Veyr")
            (source_kb_dir / "terms_map.json").write_text("{}", encoding="utf-8")

            captured: dict[str, Path] = {}

            def fake_build(**kwargs: object) -> BuildResult:
                knowledge_base_dir = kwargs["knowledge_base_dir"]
                self.assertIsInstance(knowledge_base_dir, Path)
                captured["knowledge_base_dir"] = knowledge_base_dir
                return make_build_result(knowledge_base_dir)

            result = build_task7_eval_corpus(
                source_kb_dir=source_kb_dir,
                output_dir=output_dir,
                build_index_fn=fake_build,
            )

            self.assertTrue((source_kb_dir / "elyra-noctis.md").exists())
            self.assertTrue((source_kb_dir / "the-hollow-eclipse.md").exists())
            self.assertTrue((source_kb_dir / "skyball.md").exists())
            self.assertFalse((result.eval_kb_dir / "elyra-noctis.md").exists())
            self.assertFalse((result.eval_kb_dir / "the-hollow-eclipse.md").exists())
            self.assertFalse((result.eval_kb_dir / "skyball.md").exists())
            self.assertTrue((result.eval_kb_dir / "caelan-veyr.md").exists())
            self.assertTrue((result.eval_kb_dir / "terms_map.json").exists())
            self.assertEqual(result.gap_manifest.removed_documents, ("elyra-noctis.md", "the-hollow-eclipse.md", "skyball.md"))
            self.assertEqual(captured["knowledge_base_dir"], result.eval_kb_dir)
            self.assertTrue(result.gap_manifest_path.exists())

    def test_load_golden_questions_reads_expected_answer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            golden_path = Path(temp_dir) / "golden_questions.json"
            golden_path.write_text(
                json.dumps(
                    [
                        {
                            "id": "positive_stub",
                            "query": "Who is Caelan Veyr's father?",
                            "expected_outcome": "answer",
                            "expected_answer": "Caelan Veyr's father is Darius Veyr.",
                            "expected_keywords": ["darius veyr"],
                            "forbidden_keywords": ["i don't know"],
                            "expected_source_contains": ["caelan-veyr.md"],
                            "review_notes": "loader smoke test",
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            questions = load_golden_questions(golden_path)

            self.assertEqual(len(questions), 1)
            self.assertEqual(questions[0].expected_answer, "Caelan Veyr's father is Darius Veyr.")

    def test_rule_based_positive_pass(self) -> None:
        question = GoldenQuestion(
            id="positive_caelan_father",
            query="Who is Caelan Veyr's father?",
            expected_outcome="answer",
            expected_answer="Caelan Veyr's father is Darius Veyr.",
            expected_keywords=("darius veyr",),
            forbidden_keywords=("i don't know",),
            expected_source_contains=("caelan-veyr.md",),
            review_notes="positive pass",
        )
        answer = make_answer(
            question=question.query,
            answer_text="Caelan Veyr's father is Darius Veyr.",
            sources=["Caelan Veyr — knowledge_base/caelan-veyr.md (Details)"],
            is_fallback=False,
        )

        record = evaluate_question(question, answer)

        self.assertEqual(record.rule_eval, PASS_LABEL)
        self.assertEqual(record.final_eval, PASS_LABEL)

    def test_rule_based_negative_pass(self) -> None:
        question = GoldenQuestion(
            id="negative_elyra_eye_color",
            query="Какого цвета глаза у Elyra Noctis?",
            expected_outcome="fallback",
            expected_answer="Я не знаю.",
            expected_keywords=(),
            forbidden_keywords=("heterochromia", "left eye is blue"),
            expected_source_contains=(),
            review_notes="negative pass",
        )
        answer = make_answer(
            question=question.query,
            answer_text="Я не знаю.",
            sources=["нет релевантных фрагментов"],
            is_fallback=True,
        )

        record = evaluate_question(question, answer)

        self.assertEqual(record.rule_eval, PASS_LABEL)
        self.assertEqual(record.final_eval, PASS_LABEL)
        self.assertEqual(record.actual_outcome, "fallback")

    def test_fail_for_unexpected_grounded_answer(self) -> None:
        question = GoldenQuestion(
            id="negative_hollow_eclipse_creatures",
            query="What creatures does the Hollow Eclipse create from its outer layer?",
            expected_outcome="fallback",
            expected_answer="I don't know.",
            expected_keywords=(),
            forbidden_keywords=("eclipseborn",),
            expected_source_contains=(),
            review_notes="negative fail",
        )
        answer = make_answer(
            question=question.query,
            answer_text="The Hollow Eclipse creates Eclipseborn from its outer layer.",
            sources=["The Hollow Eclipse — knowledge_base/the-hollow-eclipse.md (Details)"],
            is_fallback=False,
        )

        record = evaluate_question(question, answer)

        self.assertEqual(record.rule_eval, FAIL_LABEL)
        self.assertEqual(record.final_eval, FAIL_LABEL)

    def test_review_needed_for_partial_positive_match(self) -> None:
        question = GoldenQuestion(
            id="positive_archon_velis_teachings",
            query="Which leader's teachings were implemented by Veylspire to maintain order?",
            expected_outcome="answer",
            expected_answer="Veylspire implemented teachings left by Archon Velis.",
            expected_keywords=("archon velis",),
            forbidden_keywords=("i don't know",),
            expected_source_contains=("elyndra.md",),
            review_notes="partial positive",
        )
        answer = make_answer(
            question=question.query,
            answer_text="The teachings were implemented by Velis to maintain order.",
            sources=["Elyndra — knowledge_base/elyndra.md (Details)"],
            is_fallback=False,
        )

        record = evaluate_question(question, answer)

        self.assertEqual(record.rule_eval, REVIEW_LABEL)
        self.assertEqual(record.final_eval, REVIEW_LABEL)

    def test_fallback_detection_for_ru_and_en_answers(self) -> None:
        scenarios = (
            ("Какого цвета глаза у Elyra Noctis?", "Я не знаю.", True),
            ("What kind of stadium is Skyball played in?", "I don't know.", True),
            (
                "Сколько раундов играют в Skyball во время Endless Truce?",
                "Информации о количестве раундов в игре Skyball во время Endless Truce нет.",
                False,
            ),
        )

        for query, answer_text, is_fallback in scenarios:
            with self.subTest(query=query, is_fallback=is_fallback):
                question = GoldenQuestion(
                    id=f"case_{hash(query)}",
                    query=query,
                    expected_outcome="fallback",
                    expected_answer="Я не знаю." if "Какого" in query or "Сколько" in query else "I don't know.",
                    expected_keywords=(),
                    forbidden_keywords=("open-air water sphere stadium",),
                    expected_source_contains=(),
                    review_notes="fallback detection",
                )
                answer = make_answer(
                    question=query,
                    answer_text=answer_text,
                    sources=["no relevant context found"],
                    is_fallback=is_fallback,
                )
                record = evaluate_question(question, answer)
                self.assertEqual(record.actual_outcome, "fallback")

    def test_manual_review_queue_generation_for_review_needed_and_unavailable_judge(self) -> None:
        question = GoldenQuestion(
            id="positive_partial_manual_review",
            query="Which leader's teachings were implemented by Veylspire to maintain order?",
            expected_outcome="answer",
            expected_answer="Veylspire implemented teachings left by Archon Velis.",
            expected_keywords=("archon velis",),
            forbidden_keywords=("i don't know",),
            expected_source_contains=("elyndra.md",),
            review_notes="manual review queue",
        )
        answer = make_answer(
            question=question.query,
            answer_text="The teachings were implemented by Velis.",
            sources=["Elyndra — knowledge_base/elyndra.md (Details)"],
            is_fallback=False,
        )

        def judge_runner(_: GoldenQuestion, __: RagAnswer) -> JudgeDecision:
            return JudgeDecision(label=REVIEW_LABEL, reason="judge_still_uncertain")

        review_record = evaluate_question(question, answer, judge_runner=judge_runner)
        unavailable_record = evaluate_question(question, answer, judge_runner=None)
        markdown = render_manual_review_md([review_record, unavailable_record])

        self.assertEqual(review_record.judge_eval, REVIEW_LABEL)
        self.assertEqual(review_record.final_eval, REVIEW_LABEL)
        self.assertEqual(unavailable_record.judge_eval, "unavailable")
        self.assertEqual(unavailable_record.final_eval, REVIEW_LABEL)
        self.assertIn("judge_eval: `review_needed`", markdown)
        self.assertIn("judge_eval: `unavailable`", markdown)


if __name__ == "__main__":
    unittest.main()
