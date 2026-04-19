from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from task4_rag import (  # noqa: E402
    ProtectionTrace,
    RetrievedHit,
    build_definition_expansion_query,
    build_fallback_answer,
    detect_question_language,
    parse_model_response,
    prepare_context_hits,
    should_retry_definition_query,
)


def make_hit(
    *,
    score: float = 0.613401,
    source_path: str = "knowledge_base/caelan-veyr.md",
    title: str = "Caelan Veyr",
    section: str = "Details",
    text: str = "Caelan Veyr's father is Darius Veyr.",
    retrieval_quality: str = "content",
    related_entities: tuple[str, ...] = (),
) -> RetrievedHit:
    return RetrievedHit(
        rank=1,
        score=score,
        chunk_id="caelan-veyr::details::000",
        source_path=source_path,
        title=title,
        section=section,
        retrieval_quality=retrieval_quality,
        text=text,
        related_entities=related_entities,
    )


def make_trace(filter_reason: str | None = None) -> ProtectionTrace:
    return ProtectionTrace(
        mode="full",
        preprompt_enabled=True,
        sanitize_enabled=True,
        postfilter_enabled=True,
        hit_traces=(),
        filter_reason=filter_reason,
    )


class Task4RagTests(unittest.TestCase):
    def test_detect_question_language(self) -> None:
        self.assertEqual(detect_question_language("Who is Caelan Veyr's father?"), "en")
        self.assertEqual(detect_question_language("Кто отец Каэлана Вейра?"), "ru")

    def test_parse_model_response_uses_fallback_payload_for_russian_no_answer(self) -> None:
        answer = parse_model_response(
            question="Назови столицу Франции.",
            raw_response=(
                "Краткие шаги:\n"
                "1. Попробовал ответить.\n\n"
                "Ответ:\n"
                "Я не знаю.\n\n"
                "Источники:\n"
                "- Caelan Veyr — knowledge_base/caelan-veyr.md (Details)"
            ),
            selected_hits=[make_hit()],
            protection_trace=make_trace(),
        )

        self.assertTrue(answer.is_fallback)
        self.assertEqual(answer.answer, "Я не знаю.")
        self.assertEqual(answer.steps, [
            "Выполнил поиск по базе знаний.",
            "Релевантных фрагментов для ответа не нашёл.",
        ])
        self.assertEqual(answer.sources, ["нет релевантных фрагментов"])

    def test_parse_model_response_uses_fallback_payload_for_english_no_answer(self) -> None:
        answer = parse_model_response(
            question="What is the capital of France?",
            raw_response=(
                "Краткие шаги:\n"
                "1. Tried to answer.\n\n"
                "Ответ:\n"
                "I don't know.\n\n"
                "Источники:\n"
                "- Security Incident Memo — artifacts/task5/demo_kb/malicious_document.md (Details)"
            ),
            selected_hits=[make_hit()],
            protection_trace=make_trace(),
        )

        self.assertTrue(answer.is_fallback)
        self.assertEqual(answer.answer, "I don't know.")
        self.assertEqual(answer.steps, [
            "Searched the knowledge base.",
            "Did not find relevant fragments for the answer.",
        ])
        self.assertEqual(answer.sources, ["no relevant context found"])

    def test_parse_model_response_keeps_selected_hits_for_grounded_answer(self) -> None:
        answer = parse_model_response(
            question="Who is Caelan Veyr's father?",
            raw_response=(
                "Краткие шаги:\n"
                "1. Checked the retrieved context.\n\n"
                "Ответ:\n"
                "Caelan Veyr's father is Darius Veyr.\n\n"
                "Источники:\n"
                "- Model invented source"
            ),
            selected_hits=[make_hit()],
            protection_trace=make_trace(),
        )

        self.assertFalse(answer.is_fallback)
        self.assertEqual(answer.answer, "Caelan Veyr's father is Darius Veyr.")
        self.assertEqual(answer.sources, ["Caelan Veyr — knowledge_base/caelan-veyr.md (Details)"])

    def test_parse_model_response_replaces_grounded_steps_when_language_mismatches_question(self) -> None:
        answer = parse_model_response(
            question="Кто отец Каэлана Вейра?",
            raw_response=(
                "Краткие шаги:\n"
                "1. Checked the retrieved context.\n"
                "2. Found the answer in the first chunk.\n\n"
                "Ответ:\n"
                "Отцом Каэлана Вейра является Darius Veyr.\n\n"
                "Источники:\n"
                "- Model invented source"
            ),
            selected_hits=[make_hit()],
            protection_trace=make_trace(),
        )

        self.assertFalse(answer.is_fallback)
        self.assertEqual(answer.steps, [
            "Выполнил поиск по базе знаний и отобрал самые релевантные чанки.",
            "Использовал фрагмент Caelan Veyr из раздела Details.",
            "Сформулировал ответ только по retrieved-контексту.",
        ])
        self.assertEqual(answer.sources, ["Caelan Veyr — knowledge_base/caelan-veyr.md (Details)"])

    def test_parse_model_response_detects_contextual_no_answer_phrasing(self) -> None:
        answer = parse_model_response(
            question="What is the largest ocean on Earth?",
            raw_response=(
                "Краткие шаги:\n"
                "1. Checked the retrieved context.\n\n"
                "Ответ:\n"
                "There is no information about the largest ocean on Earth in the context.\n\n"
                "Источники:\n"
                "- Isola Veyn — artifacts/task5/demo_kb/isola-veyn.md (Overview)"
            ),
            selected_hits=[make_hit()],
            protection_trace=make_trace(),
        )

        self.assertTrue(answer.is_fallback)
        self.assertEqual(answer.answer, "I don't know.")
        self.assertEqual(answer.steps, [
            "Searched the knowledge base.",
            "Did not find relevant fragments for the answer.",
        ])
        self.assertEqual(answer.sources, ["no relevant context found"])

    def test_parse_model_response_detects_russian_contextual_no_answer_for_english_question(self) -> None:
        answer = parse_model_response(
            question="What is the largest ocean on Earth?",
            raw_response=(
                "Краткие шаги:\n"
                "1. Проверил предоставленный контекст.\n"
                "2. Ответил только по найденным фрагментам.\n\n"
                "Ответ:\n"
                "На основе переданного контекста невозможно ответить на вопрос о самом большом океане на Земле.\n\n"
                "Источники:\n"
                "- Isola Veyn — artifacts/task5/demo_kb/isola-veyn.md (Overview)"
            ),
            selected_hits=[make_hit()],
            protection_trace=make_trace(),
        )

        self.assertTrue(answer.is_fallback)
        self.assertEqual(answer.answer, "I don't know.")
        self.assertEqual(answer.steps, [
            "Searched the knowledge base.",
            "Did not find relevant fragments for the answer.",
        ])
        self.assertEqual(answer.sources, ["no relevant context found"])

    def test_parse_model_response_detects_russian_information_absence_for_english_question(self) -> None:
        answer = parse_model_response(
            question="Who is Tidus? He is the main character as I may recall",
            raw_response=(
                "Краткие шаги:\n"
                "1. Searched the knowledge base and selected the most relevant chunks.\n"
                "2. Used the fragment Darius Veyr from the Overview section.\n"
                "3. Formulated the answer using only retrieved context.\n\n"
                "Ответ:\n"
                "Информации о персонаже Tidus нет в предоставленном контексте.\n\n"
                "Источники:\n"
                "- Darius Veyr — knowledge_base/darius-veyr.md (Overview)\n"
                "- Torren Kaid — knowledge_base/torren-kaid.md (Overview)\n"
                "- Garron Vale — knowledge_base/garron-vale.md (Overview)"
            ),
            selected_hits=[make_hit()],
            protection_trace=make_trace(),
        )

        self.assertTrue(answer.is_fallback)
        self.assertEqual(answer.answer, "I don't know.")
        self.assertEqual(answer.steps, [
            "Searched the knowledge base.",
            "Did not find relevant fragments for the answer.",
        ])
        self.assertEqual(answer.sources, ["no relevant context found"])

    def test_build_fallback_answer_keeps_contract_for_different_filter_reasons(self) -> None:
        scenarios = (
            ("What is the capital of France?", "score_threshold", "I don't know.", "no relevant context found"),
            ("Назови столицу Франции.", "all_candidate_chunks_filtered", "Я не знаю.", "нет релевантных фрагментов"),
        )

        for question, filter_reason, expected_answer, expected_source in scenarios:
            with self.subTest(question=question, filter_reason=filter_reason):
                answer = build_fallback_answer(
                    question=question,
                    retrieved_hits=[make_hit()],
                    protection_trace=make_trace(filter_reason=filter_reason),
                )
                self.assertTrue(answer.is_fallback)
                self.assertEqual(answer.answer, expected_answer)
                self.assertEqual(answer.sources, [expected_source])

    def test_prepare_context_hits_keeps_best_content_hit_after_quality_filter(self) -> None:
        selection = prepare_context_hits(
            question="What ritual sends souls to the Veilward?",
            retrieved_hits=[
                make_hit(
                    score=0.95,
                    source_path="artifacts/task7/eval_kb/veilward.md",
                    title="Veilward",
                    section="Overview",
                    retrieval_quality="generic_summary",
                    text="Veilward is preserved in the archive as a concept woven into history.",
                ),
                make_hit(
                    score=1.08,
                    source_path="artifacts/task7/eval_kb/veilward.md",
                    title="Veilward",
                    section="Details",
                    retrieval_quality="generic_summary",
                    text="Recovered notes about Veilward remain fragmentary.",
                ),
                make_hit(
                    score=1.28,
                    source_path="artifacts/task7/eval_kb/the-luminous-order.md",
                    title="The Luminous Order",
                    section="Details",
                    text="Temples of The Luminous Order are found throughout Elyndra.",
                ),
            ],
            max_context_chunks=3,
            score_threshold=1.45,
            protection_mode="full",
        )

        self.assertEqual(len(selection.selected_hits), 1)
        self.assertEqual(selection.selected_hits[0].title, "The Luminous Order")
        self.assertIsNone(selection.protection_trace.filter_reason)

    def test_prepare_context_hits_keeps_weak_hit_when_title_overlaps_question(self) -> None:
        selection = prepare_context_hits(
            question="What is the central temple of The Luminous Order?",
            retrieved_hits=[
                make_hit(
                    score=1.08,
                    source_path="artifacts/task7/eval_kb/the-luminous-order.md",
                    title="The Luminous Order",
                    section="Details",
                    text="The central temple of The Luminous Order is Veylspire.",
                ),
            ],
            max_context_chunks=3,
            score_threshold=1.45,
            protection_mode="full",
        )

        self.assertEqual(len(selection.selected_hits), 1)
        self.assertIsNone(selection.protection_trace.filter_reason)

    def test_prepare_context_hits_keeps_definition_hit_when_entity_is_mentioned_in_content(self) -> None:
        selection = prepare_context_hits(
            question="What is the Truce of Ash?",
            retrieved_hits=[
                make_hit(
                    score=1.38,
                    source_path="artifacts/task7/eval_kb/elyndra.md",
                    title="Elyndra",
                    section="Details",
                    text="Only the ritual known as the Last Invocation would provide a reprieve from The Hollow Eclipse's terror (referred to as The Truce of Ash).",
                ),
            ],
            max_context_chunks=3,
            score_threshold=1.45,
            protection_mode="full",
        )

        self.assertEqual(len(selection.selected_hits), 1)
        self.assertIsNone(selection.protection_trace.filter_reason)

    def test_prepare_context_hits_keeps_hit_with_query_support_tokens_in_content(self) -> None:
        selection = prepare_context_hits(
            question="Which leader's teachings were implemented by Veylspire to maintain order?",
            retrieved_hits=[
                make_hit(
                    score=1.36,
                    source_path="artifacts/task7/eval_kb/elyndra.md",
                    title="Elyndra",
                    section="Details",
                    text="The teachings of The Luminous Order, said to have been left by Asterreach's leader, Archon Velis, were implemented by Veylspire to maintain order.",
                ),
            ],
            max_context_chunks=3,
            score_threshold=1.45,
            protection_mode="full",
        )

        self.assertEqual(len(selection.selected_hits), 1)
        self.assertIsNone(selection.protection_trace.filter_reason)

    def test_prepare_context_hits_keeps_specific_query_hit_without_support_overlap_gate(self) -> None:
        selection = prepare_context_hits(
            question="What ritual sends souls to the Veilward?",
            retrieved_hits=[
                make_hit(
                    score=1.29,
                    source_path="artifacts/task7/eval_kb/elyndra.md",
                    title="Elyndra",
                    section="Details",
                    text="Only the ritual known as the Last Invocation would provide a reprieve from The Hollow Eclipse's terror.",
                ),
            ],
            max_context_chunks=3,
            score_threshold=1.45,
            protection_mode="full",
        )

        self.assertEqual(len(selection.selected_hits), 1)
        self.assertEqual(selection.selected_hits[0].title, "Elyndra")
        self.assertIsNone(selection.protection_trace.filter_reason)

    def test_prepare_context_hits_keeps_stronger_non_overlapping_hit_below_weak_support_threshold(self) -> None:
        selection = prepare_context_hits(
            question="What is kept inside a Chamber of the Dreambound?",
            retrieved_hits=[
                make_hit(
                    score=0.96,
                    source_path="artifacts/task7/eval_kb/sanctum-of-ordeals.md",
                    title="Sanctum of Ordeals",
                    section="Details",
                    text="Aim: To descend towards the Chamber of the Dreambound.",
                ),
                make_hit(
                    score=1.04,
                    source_path="artifacts/task7/eval_kb/the-luminous-order.md",
                    title="The Luminous Order",
                    section="Details",
                    text="A Chamber of the Dreambound contains a statue that houses a willingly-given human soul.",
                ),
            ],
            max_context_chunks=3,
            score_threshold=1.45,
            protection_mode="full",
        )

        self.assertEqual(len(selection.selected_hits), 2)
        self.assertIsNone(selection.protection_trace.filter_reason)

    def test_definition_query_retry_uses_related_entities_from_generic_title_hit(self) -> None:
        retrieved_hits = [
            make_hit(
                score=0.46,
                source_path="artifacts/task7/eval_kb/truce-of-ash.md",
                title="Truce of Ash",
                section="Overview",
                retrieval_quality="generic_summary",
                text="Truce of Ash is preserved in the archive as a concept woven into history.",
                related_entities=("Elyndra", "The Luminous Order", "The Hollow Eclipse"),
            )
        ]
        query_title_tokens = {"truce", "ash"}

        self.assertTrue(
            should_retry_definition_query(
                query_title_tokens=query_title_tokens,
                query_support_tokens=set(),
                retrieved_hits=retrieved_hits,
            )
        )
        self.assertEqual(
            build_definition_expansion_query(
                question="What is the Truce of Ash?",
                query_title_tokens=query_title_tokens,
                retrieved_hits=retrieved_hits,
            ),
            "What is the Truce of Ash? Elyndra The Luminous Order The Hollow Eclipse",
        )


if __name__ == "__main__":
    unittest.main()
