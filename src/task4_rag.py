from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import requests
from langchain_community.chat_models import ChatOllama
from langchain_community.llms.ollama import OllamaEndpointNotFoundError
from langchain_community.vectorstores import FAISS
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from task3_indexing import DEFAULT_EMBEDDING_MODEL, create_embeddings, load_index, strip_chunk_prefix


DEFAULT_OLLAMA_MODEL = "qwen2.5:7b-instruct"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_TOP_K = 4
DEFAULT_MAX_CONTEXT_CHUNKS = 3
DEFAULT_SCORE_THRESHOLD = 1.45
DEFAULT_TEMPERATURE = 0.1
DEFAULT_NUM_CTX = 4096
DEFAULT_NUM_PREDICT = 350
DEFAULT_TIMEOUT_SECONDS = 120
MAX_QUERY_LENGTH = 1000
QuestionLanguage = Literal["ru", "en"]
CYRILLIC_PATTERN = re.compile(r"[А-Яа-яЁё]")
NO_ANSWER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bя не знаю\b", re.IGNORECASE),
    re.compile(r"\bi don't know\b", re.IGNORECASE),
    re.compile(r"\bнет (?:достаточной )?информац", re.IGNORECASE),
    re.compile(r"\bв (?:этом|данном) контексте нет\b", re.IGNORECASE),
    re.compile(r"\bno (?:relevant|enough )?information\b", re.IGNORECASE),
    re.compile(r"\bnot enough information\b", re.IGNORECASE),
    re.compile(r"\bnot (?:present|available) in (?:the )?context\b", re.IGNORECASE),
)
FALLBACK_ANSWER_BY_LANGUAGE: dict[QuestionLanguage, str] = {
    "ru": "Я не знаю.",
    "en": "I don't know.",
}
FALLBACK_SOURCE_BY_LANGUAGE: dict[QuestionLanguage, str] = {
    "ru": "нет релевантных фрагментов",
    "en": "no relevant context found",
}
FALLBACK_STEPS_BY_LANGUAGE: dict[QuestionLanguage, list[str]] = {
    "ru": [
        "Выполнил поиск по базе знаний.",
        "Релевантных фрагментов для ответа не нашёл.",
    ],
    "en": [
        "Searched the knowledge base.",
        "Did not find relevant fragments for the answer.",
    ],
}
DEFAULT_GROUNDED_STEPS_BY_LANGUAGE: dict[QuestionLanguage, tuple[str, str]] = {
    "ru": (
        "Выполнил поиск по базе знаний и отобрал самые релевантные чанки.",
        "Сформулировал ответ только по retrieved-контексту.",
    ),
    "en": (
        "Searched the knowledge base and selected the most relevant chunks.",
        "Formulated the answer using only retrieved context.",
    ),
}

SYSTEM_PROMPT = """Ты — помощник по synthetic knowledge base проекта Task 4.
Отвечай только на основе переданного контекста.
Не используй внешние знания и не додумывай недостающие факты.
Если в контексте недостаточно информации, ответь честным fallback на том же языке, что и вопрос пользователя.
Пиши на том же языке, что и вопрос пользователя.
Всегда возвращай ответ строго в формате:

Краткие шаги:
1. ...
2. ...

Ответ:
...

Источники:
- Title — source_path (Section)

Правила:
- В разделе "Краткие шаги" должно быть от 1 до 3 коротких пунктов.
- В разделе "Ответ" дай короткий grounded-ответ без лишних деталей.
- В разделе "Источники" перечисли только реально использованные фрагменты контекста.
- Если ответа нет, напиши:
  Краткие шаги:
  1. ... на языке вопроса пользователя
  2. ... на языке вопроса пользователя

  Ответ:
  ... локализованный fallback на языке вопроса пользователя

  Источники:
  - ... локализованный fallback source на языке вопроса пользователя
"""


@dataclass(frozen=True)
class RagConfig:
    index_dir: Path
    embedding_model_name: str = DEFAULT_EMBEDDING_MODEL
    ollama_model: str = DEFAULT_OLLAMA_MODEL
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL
    top_k: int = DEFAULT_TOP_K
    max_context_chunks: int = DEFAULT_MAX_CONTEXT_CHUNKS
    score_threshold: float = DEFAULT_SCORE_THRESHOLD
    temperature: float = DEFAULT_TEMPERATURE
    num_ctx: int = DEFAULT_NUM_CTX
    num_predict: int = DEFAULT_NUM_PREDICT
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if self.top_k <= 0:
            raise ValueError("top_k must be positive.")
        if self.max_context_chunks <= 0:
            raise ValueError("max_context_chunks must be positive.")
        if self.score_threshold <= 0:
            raise ValueError("score_threshold must be positive.")
        if self.temperature < 0:
            raise ValueError("temperature must be non-negative.")
        if self.num_ctx <= 0:
            raise ValueError("num_ctx must be positive.")
        if self.num_predict <= 0:
            raise ValueError("num_predict must be positive.")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive.")


class Task4RagError(RuntimeError):
    """Base error for Task 4 runtime failures."""


class Task4ConfigurationError(Task4RagError):
    """Raised when Task 4 runtime configuration is invalid."""


class Task4GenerationError(Task4RagError):
    """Raised when the local LLM call fails."""


@dataclass(frozen=True)
class RetrievedHit:
    rank: int
    score: float
    chunk_id: str
    source_path: str
    title: str
    section: str
    text: str

    @property
    def source_label(self) -> str:
        return f"{self.title} — {self.source_path} ({self.section})"


@dataclass(frozen=True)
class RagAnswer:
    question: str
    steps: list[str]
    answer: str
    sources: list[str]
    is_fallback: bool
    retrieved_hits: list[RetrievedHit]
    raw_response: str


@dataclass
class RagBot:
    config: RagConfig
    index: FAISS
    llm: ChatOllama

    def answer_question(self, question: str) -> RagAnswer:
        normalized_question = question.strip()
        if not normalized_question:
            raise ValueError("Question must not be empty.")
        if len(normalized_question) > MAX_QUERY_LENGTH:
            raise ValueError(f"Question must not exceed {MAX_QUERY_LENGTH} characters.")

        retrieved_hits = retrieve_hits(self.index, normalized_question, self.config.top_k)
        selected_hits = select_context_hits(
            retrieved_hits=retrieved_hits,
            max_context_chunks=self.config.max_context_chunks,
            score_threshold=self.config.score_threshold,
        )
        if not selected_hits:
            return build_fallback_answer(normalized_question, retrieved_hits)

        messages = build_messages(normalized_question, selected_hits)
        raw_response = invoke_ollama(self.llm, messages)
        parsed_answer = parse_model_response(
            question=normalized_question,
            raw_response=raw_response,
            selected_hits=selected_hits,
        )
        return parsed_answer


@dataclass(frozen=True)
class FewShotExample:
    context_blocks: list[str]
    question: str
    response: str


def build_context_block(hit: RetrievedHit, block_index: int) -> str:
    return (
        f"[Context {block_index}]\n"
        f"Title: {hit.title}\n"
        f"source_path: {hit.source_path}\n"
        f"Section: {hit.section}\n"
        f"Score: {hit.score:.6f}\n"
        f"Content:\n{hit.text.strip()}"
    )


FEW_SHOT_EXAMPLES = (
    FewShotExample(
        context_blocks=(
            [
                build_context_block(
                    RetrievedHit(
                        rank=1,
                        score=0.613401,
                        chunk_id="caelan-veyr::details::000",
                        source_path="knowledge_base/caelan-veyr.md",
                        title="Caelan Veyr",
                        section="Details",
                        text=(
                            "To Caelan Veyr' dismay, he has similarities to his father, who tended to ignore "
                            "responsibility, take things easy, and never worry about the present situation "
                            "instead of leaving things for future. Caelan Veyr' resemblance to his father is "
                            "pointed out by Garron Vale. Despite having been verbally offensive, at heart, "
                            "Darius Veyr was proud of his son and his resolve."
                        ),
                    ),
                    1,
                ),
                build_context_block(
                    RetrievedHit(
                        rank=2,
                        score=0.919829,
                        chunk_id="garron-vale::overview::000",
                        source_path="knowledge_base/garron-vale.md",
                        title="Garron Vale",
                        section="Overview",
                        text=(
                            "Garron Vale watches over Caelan Veyr while concealing his mysterious past tying him "
                            "into the stories of Arcton Veyr and Caelan Veyr' father, Darius Veyr."
                        ),
                    ),
                    2,
                ),
            ]
        ),
        question="Who is Caelan Veyr's father?",
        response=(
            "Краткие шаги:\n"
            "1. Проверил retrieved-фрагменты про прошлое Caelan Veyr и его семью.\n"
            "2. В контексте прямо названо имя его отца: Darius Veyr.\n"
            "3. Сформулировал ответ без добавления внешних фактов.\n\n"
            "Ответ:\n"
            "Caelan Veyr's father is Darius Veyr.\n\n"
            "Источники:\n"
            "- Caelan Veyr — knowledge_base/caelan-veyr.md (Details)\n"
            "- Garron Vale — knowledge_base/garron-vale.md (Overview)"
        ),
    ),
    FewShotExample(
        context_blocks=(
            [
                build_context_block(
                    RetrievedHit(
                        rank=1,
                        score=0.428577,
                        chunk_id="the-hollow-eclipse::overview::000",
                        source_path="knowledge_base/the-hollow-eclipse.md",
                        title="The Hollow Eclipse",
                        section="Overview",
                        text=(
                            "The Hollow Eclipse is preserved in the archive as a concept woven into Elyndran "
                            "history, ritual memory, and the synthetic world model prepared for retrieval."
                        ),
                    ),
                    1,
                ),
                build_context_block(
                    RetrievedHit(
                        rank=2,
                        score=0.609276,
                        chunk_id="the-hollow-eclipse::details::000",
                        source_path="knowledge_base/the-hollow-eclipse.md",
                        title="The Hollow Eclipse",
                        section="Details",
                        text=(
                            "The Hollow Eclipse has a whale-like body that it moves with a pair of clawed arms, "
                            "as well as hind legs resembling pectoral fins for movement in water. It carries part "
                            "of a city on its body and can create smaller creatures, Eclipseborn, from its outer layer."
                        ),
                    ),
                    2,
                ),
            ]
        ),
        question="What is the Hollow Eclipse?",
        response=(
            "Краткие шаги:\n"
            "1. Проверил overview и details по сущности The Hollow Eclipse.\n"
            "2. В контексте она описана как крупная чудовищная сущность с whale-like body.\n"
            "3. Сжал описание до короткого grounded-ответа.\n\n"
            "Ответ:\n"
            "The Hollow Eclipse is a gigantic monstrous entity in Elyndran history, described as a whale-like creature that can create smaller Eclipseborn from its outer layer.\n\n"
            "Источники:\n"
            "- The Hollow Eclipse — knowledge_base/the-hollow-eclipse.md (Overview)\n"
            "- The Hollow Eclipse — knowledge_base/the-hollow-eclipse.md (Details)"
        ),
    ),
)


def load_bot(config: RagConfig) -> RagBot:
    if not config.index_dir.exists():
        raise Task4ConfigurationError(f"Index directory does not exist: {config.index_dir}")

    embeddings = create_embeddings(config.embedding_model_name)
    index = load_index(index_dir=config.index_dir, embeddings=embeddings)
    llm = ChatOllama(
        model=config.ollama_model,
        base_url=config.ollama_base_url,
        temperature=config.temperature,
        num_ctx=config.num_ctx,
        num_predict=config.num_predict,
        timeout=config.timeout_seconds,
    )
    return RagBot(config=config, index=index, llm=llm)


def retrieve_hits(index: FAISS, question: str, top_k: int) -> list[RetrievedHit]:
    retrieved_hits: list[RetrievedHit] = []
    raw_matches = index.similarity_search_with_score(question, k=top_k)
    for rank, (document, score) in enumerate(raw_matches, start=1):
        metadata = document.metadata
        retrieved_hits.append(
            RetrievedHit(
                rank=rank,
                score=float(score),
                chunk_id=str(metadata["chunk_id"]),
                source_path=str(metadata["source_path"]),
                title=str(metadata["title"]),
                section=str(metadata["section"]),
                text=strip_chunk_prefix(document.page_content),
            )
        )
    return retrieved_hits


def select_context_hits(
    retrieved_hits: list[RetrievedHit],
    max_context_chunks: int,
    score_threshold: float,
) -> list[RetrievedHit]:
    if not retrieved_hits:
        return []
    if retrieved_hits[0].score > score_threshold:
        return []

    selected_hits = [hit for hit in retrieved_hits if hit.score <= score_threshold]
    if not selected_hits:
        return []
    return selected_hits[:max_context_chunks]


def build_messages(question: str, selected_hits: list[RetrievedHit]) -> list[BaseMessage]:
    messages: list[BaseMessage] = [SystemMessage(content=SYSTEM_PROMPT)]
    for example in FEW_SHOT_EXAMPLES:
        messages.append(HumanMessage(content=build_example_prompt(example)))
        messages.append(AIMessage(content=example.response))

    messages.append(HumanMessage(content=build_user_prompt(question, selected_hits)))
    return messages


def build_example_prompt(example: FewShotExample) -> str:
    context_block = "\n\n".join(example.context_blocks)
    return f"Контекст:\n{context_block}\n\nВопрос:\n{example.question}"


def build_user_prompt(question: str, selected_hits: list[RetrievedHit]) -> str:
    context_blocks = [
        build_context_block(hit, block_index)
        for block_index, hit in enumerate(selected_hits, start=1)
    ]
    joined_context = "\n\n".join(context_blocks)
    return f"Контекст:\n{joined_context}\n\nВопрос:\n{question}"


def invoke_ollama(llm: ChatOllama, messages: list[BaseMessage]) -> str:
    try:
        response = llm.invoke(messages)
    except OllamaEndpointNotFoundError as error:
        raise Task4GenerationError(
            "Ollama endpoint is not available. Start Ollama and ensure the model is pulled."
        ) from error
    except requests.exceptions.RequestException as error:
        raise Task4GenerationError("Failed to reach the local Ollama service.") from error
    except ValueError as error:
        raise Task4GenerationError("Ollama returned an invalid response.") from error

    content = response.content
    if not isinstance(content, str):
        raise Task4GenerationError("Ollama returned a non-text response.")
    normalized_content = content.strip()
    if not normalized_content:
        raise Task4GenerationError("Ollama returned an empty response.")
    return normalized_content


def parse_model_response(
    question: str,
    raw_response: str,
    selected_hits: list[RetrievedHit],
) -> RagAnswer:
    parsed_sections = split_response_sections(raw_response)
    steps = normalize_steps(parsed_sections.get("Краткие шаги", ""))
    answer_text = parsed_sections.get("Ответ", "").strip()

    if not steps:
        steps = build_default_steps(question, selected_hits)
    if not answer_text:
        answer_text = raw_response.strip()
    is_fallback = is_no_answer_text(answer_text)
    if is_fallback:
        fallback_payload = build_fallback_payload(question)
        steps = fallback_payload["steps"]
        answer_text = fallback_payload["answer"]
        resolved_sources = fallback_payload["sources"]
    else:
        steps = normalize_grounded_steps(question, steps, selected_hits)
        resolved_sources = [hit.source_label for hit in selected_hits[:3]]

    return RagAnswer(
        question=question,
        steps=steps,
        answer=answer_text,
        sources=resolved_sources,
        is_fallback=is_fallback,
        retrieved_hits=selected_hits,
        raw_response=raw_response,
    )


def split_response_sections(raw_response: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    section_pattern = re.compile(r"^(Краткие шаги|Ответ|Источники):\s*$", re.MULTILINE)
    matches = list(section_pattern.finditer(raw_response))
    if not matches:
        return sections

    for index, match in enumerate(matches):
        section_name = match.group(1)
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(raw_response)
        sections[section_name] = raw_response[start:end].strip()
    return sections


def normalize_steps(steps_block: str) -> list[str]:
    normalized_steps: list[str] = []
    for raw_line in steps_block.splitlines():
        stripped_line = raw_line.strip()
        if not stripped_line:
            continue
        cleaned_line = re.sub(r"^\d+\.\s*", "", stripped_line)
        if cleaned_line:
            normalized_steps.append(cleaned_line)
    return normalized_steps[:3]


def build_default_steps(question: str, selected_hits: list[RetrievedHit]) -> list[str]:
    language = detect_question_language(question)
    lead_hit = selected_hits[0]
    search_step, answer_step = DEFAULT_GROUNDED_STEPS_BY_LANGUAGE[language]
    steps = [
        search_step,
        build_lead_hit_step(language, lead_hit),
        answer_step,
    ]
    return steps[:3]


def build_fallback_answer(question: str, retrieved_hits: list[RetrievedHit]) -> RagAnswer:
    fallback_payload = build_fallback_payload(question)
    return RagAnswer(
        question=question,
        steps=fallback_payload["steps"],
        answer=fallback_payload["answer"],
        sources=fallback_payload["sources"],
        is_fallback=True,
        retrieved_hits=retrieved_hits,
        raw_response="",
    )


def is_no_answer_text(answer_text: str) -> bool:
    normalized_answer = answer_text.strip()
    return any(pattern.search(normalized_answer) for pattern in NO_ANSWER_PATTERNS)


def detect_question_language(question: str) -> QuestionLanguage:
    return "ru" if CYRILLIC_PATTERN.search(question) else "en"


def is_step_language_compatible(step: str, target_language: QuestionLanguage) -> bool:
    has_cyrillic = bool(CYRILLIC_PATTERN.search(step))
    has_cjk = bool(re.search(r"[\u4e00-\u9fff]", step))
    if target_language == "ru":
        return has_cyrillic and not has_cjk
    return not has_cyrillic and not has_cjk


def normalize_grounded_steps(
    question: str,
    steps: list[str],
    selected_hits: list[RetrievedHit],
) -> list[str]:
    if not steps:
        return build_default_steps(question, selected_hits)

    target_language = detect_question_language(question)
    if all(is_step_language_compatible(step, target_language) for step in steps):
        return steps[:3]
    return build_default_steps(question, selected_hits)


def build_fallback_payload(question: str) -> dict[str, list[str] | str]:
    language = detect_question_language(question)
    return {
        "steps": list(FALLBACK_STEPS_BY_LANGUAGE[language]),
        "answer": FALLBACK_ANSWER_BY_LANGUAGE[language],
        "sources": [FALLBACK_SOURCE_BY_LANGUAGE[language]],
    }


def build_lead_hit_step(language: QuestionLanguage, lead_hit: RetrievedHit) -> str:
    if language == "ru":
        return f"Использовал фрагмент {lead_hit.title} из раздела {lead_hit.section}."
    return f"Used the fragment {lead_hit.title} from the {lead_hit.section} section."


def format_rag_answer(rag_answer: RagAnswer) -> str:
    lines = ["Краткие шаги:"]
    for index, step in enumerate(rag_answer.steps, start=1):
        lines.append(f"{index}. {step}")

    lines.append("")
    lines.append("Ответ:")
    lines.append(rag_answer.answer)
    lines.append("")
    lines.append("Источники:")
    for source in rag_answer.sources:
        lines.append(f"- {source}")
    return "\n".join(lines)
