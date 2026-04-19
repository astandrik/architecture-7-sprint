from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter


DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_EMBEDDING_MODEL_URL = "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_CHUNK_SIZE = 220
DEFAULT_CHUNK_OVERLAP = 40
DEFAULT_SEPARATORS = ["\n\n", "\n", ". ", " ", ""]
DEFAULT_ENCODING_NAME = "cl100k_base"
DEFAULT_INDEX_NAME = "index"
FAISS_INDEX_DIRNAME = "faiss_index"
REQUIRED_SECTIONS = ("Overview", "Details", "Related entities")
GENERIC_RETRIEVAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bis preserved in the archive as\b", re.IGNORECASE),
    re.compile(r"\brecovered notes about\b", re.IGNORECASE),
    re.compile(r"\bremain fragmentary\b", re.IGNORECASE),
    re.compile(r"\bsynthetic world model prepared for retrieval\b", re.IGNORECASE),
)
DEFAULT_PREVIEW_QUERIES = (
    "Who is Caelan Veyr's father?",
    "What is the Hollow Eclipse?",
    "What ritual sends souls to the Veilward?",
)


class Task3ValidationError(ValueError):
    """Raised when the synthetic knowledge base shape does not match expectations."""


@dataclass(frozen=True)
class KnowledgeBaseDocument:
    source_path: str
    title: str
    entity_type: str
    overview: str
    details: str
    related_entities: list[str]


@dataclass(frozen=True)
class ChunkRecord:
    chunk_id: str
    source_path: str
    title: str
    entity_type: str
    section: str
    retrieval_quality: str
    chunk_index: int
    char_start: int
    char_end: int
    word_count: int
    related_entities: list[str]
    text: str
    page_content: str


@dataclass(frozen=True)
class QueryMatch:
    rank: int
    score: float
    chunk_id: str
    source_path: str
    title: str
    section: str
    excerpt: str


@dataclass(frozen=True)
class BuildResult:
    embedding_model: str
    embedding_model_url: str
    embedding_dimension: int
    knowledge_base_dir: str
    documents_count: int
    chunks_count: int
    chunking_strategy: str
    chunk_size: int
    chunk_overlap: int
    build_seconds: float
    created_at: str
    preview_queries: list[dict[str, Any]]


def prepare_runtime_environment(runtime_dir: Path) -> None:
    # tiktoken requires a writable cache directory even for local token counting.
    runtime_dir.mkdir(parents=True, exist_ok=True)
    tiktoken_cache_dir = runtime_dir / "tiktoken_cache"
    tiktoken_cache_dir.mkdir(parents=True, exist_ok=True)

    resolved_runtime_dir = str(runtime_dir.resolve())
    resolved_tiktoken_cache_dir = str(tiktoken_cache_dir.resolve())

    os.environ["TMPDIR"] = resolved_runtime_dir
    os.environ["TEMP"] = resolved_runtime_dir
    os.environ["TMP"] = resolved_runtime_dir
    os.environ["TIKTOKEN_CACHE_DIR"] = resolved_tiktoken_cache_dir
    tempfile.tempdir = resolved_runtime_dir


def cleanup_runtime_environment(runtime_dir: Path) -> None:
    shutil.rmtree(runtime_dir, ignore_errors=True)


def create_embeddings(model_name: str = DEFAULT_EMBEDDING_MODEL) -> HuggingFaceEmbeddings:
    return HuggingFaceEmbeddings(
        model_name=model_name,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )


def create_text_splitter() -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        encoding_name=DEFAULT_ENCODING_NAME,
        chunk_size=DEFAULT_CHUNK_SIZE,
        chunk_overlap=DEFAULT_CHUNK_OVERLAP,
        separators=DEFAULT_SEPARATORS,
        keep_separator=False,
        add_start_index=True,
    )


def discover_markdown_files(knowledge_base_dir: Path) -> list[Path]:
    markdown_files = sorted(path for path in knowledge_base_dir.glob("*.md") if path.is_file())
    if not markdown_files:
        raise Task3ValidationError(f"No markdown files found in {knowledge_base_dir}.")
    return markdown_files


def load_knowledge_base_documents(knowledge_base_dir: Path) -> list[KnowledgeBaseDocument]:
    return [parse_knowledge_base_document(path) for path in discover_markdown_files(knowledge_base_dir)]


def parse_knowledge_base_document(path: Path) -> KnowledgeBaseDocument:
    raw_text = path.read_text(encoding="utf-8")
    title_match = re.search(r"^#\s+(.+?)\s*$", raw_text, flags=re.MULTILINE)
    if title_match is None:
        raise Task3ValidationError(f"{path}: missing top-level title heading.")

    type_match = re.search(r"^Type:\s+(.+?)\s*$", raw_text, flags=re.MULTILINE)
    if type_match is None:
        raise Task3ValidationError(f"{path}: missing `Type:` line.")

    sections = extract_sections(raw_text, path)
    related_entities = parse_related_entities(sections["Related entities"], path)

    return KnowledgeBaseDocument(
        source_path=to_repo_relative_path(path),
        title=title_match.group(1).strip(),
        entity_type=type_match.group(1).strip(),
        overview=sections["Overview"],
        details=sections["Details"],
        related_entities=related_entities,
    )


def extract_sections(raw_text: str, path: Path) -> dict[str, str]:
    heading_pattern = re.compile(r"^##\s+(Overview|Details|Related entities)\s*$", flags=re.MULTILINE)
    matches = list(heading_pattern.finditer(raw_text))
    found_sections = [match.group(1) for match in matches]

    if found_sections != list(REQUIRED_SECTIONS):
        raise Task3ValidationError(
            f"{path}: expected sections {REQUIRED_SECTIONS}, found {tuple(found_sections)}."
        )

    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(raw_text)
        content = raw_text[start:end].strip()
        if not content:
            raise Task3ValidationError(f"{path}: section `{match.group(1)}` is empty.")
        sections[match.group(1)] = content
    return sections


def parse_related_entities(section_text: str, path: Path) -> list[str]:
    related_entities = [
        line.removeprefix("- ").strip()
        for line in section_text.splitlines()
        if line.strip().startswith("- ")
    ]
    if not related_entities:
        raise Task3ValidationError(f"{path}: `Related entities` must contain bullet list items.")
    return related_entities


def build_chunk_records(
    knowledge_base_documents: list[KnowledgeBaseDocument],
    splitter: RecursiveCharacterTextSplitter,
) -> list[ChunkRecord]:
    chunk_records: list[ChunkRecord] = []

    for knowledge_base_document in knowledge_base_documents:
        for section_name, section_text in (
            ("Overview", knowledge_base_document.overview),
            ("Details", knowledge_base_document.details),
        ):
            chunk_texts = create_section_chunks(section_text, splitter)
            for chunk_index, chunk_document in enumerate(chunk_texts):
                text = chunk_document.page_content.strip()
                char_start = int(chunk_document.metadata.get("start_index", 0))
                char_end = char_start + len(text)
                chunk_id = (
                    f"{Path(knowledge_base_document.source_path).stem}"
                    f"::{section_name.lower()}::{chunk_index:03d}"
                )
                page_content = build_prefixed_chunk_text(
                    title=knowledge_base_document.title,
                    entity_type=knowledge_base_document.entity_type,
                    section=section_name,
                    text=text,
                )
                chunk_records.append(
                    ChunkRecord(
                        chunk_id=chunk_id,
                        source_path=knowledge_base_document.source_path,
                        title=knowledge_base_document.title,
                        entity_type=knowledge_base_document.entity_type,
                        section=section_name,
                        retrieval_quality=infer_retrieval_quality(section_name, text),
                        chunk_index=chunk_index,
                        char_start=char_start,
                        char_end=char_end,
                        word_count=count_words(text),
                        related_entities=knowledge_base_document.related_entities,
                        text=text,
                        page_content=page_content,
                    )
                )

    if not chunk_records:
        raise Task3ValidationError("Chunking produced no records.")

    return chunk_records


def create_section_chunks(
    section_text: str,
    splitter: RecursiveCharacterTextSplitter,
) -> list[Document]:
    base_metadata = {"start_index": 0}
    if count_words(section_text) <= DEFAULT_CHUNK_SIZE:
        return [Document(page_content=section_text.strip(), metadata=base_metadata)]
    return splitter.create_documents([section_text], metadatas=[base_metadata])


def build_prefixed_chunk_text(title: str, entity_type: str, section: str, text: str) -> str:
    return f"Title: {title}\nType: {entity_type}\nSection: {section}\n\n{text.strip()}"


def count_words(text: str) -> int:
    return len(re.findall(r"\S+", text))


def infer_retrieval_quality(section: str, text: str) -> str:
    if any(pattern.search(text) for pattern in GENERIC_RETRIEVAL_PATTERNS):
        return "generic_summary"
    if section == "Overview" and count_words(text) < 40:
        return "generic_summary"
    return "content"


def build_vector_documents(chunk_records: list[ChunkRecord]) -> list[Document]:
    return [
        Document(
            page_content=chunk_record.page_content,
            metadata={
                "chunk_id": chunk_record.chunk_id,
                "source_path": chunk_record.source_path,
                "title": chunk_record.title,
                "entity_type": chunk_record.entity_type,
                "section": chunk_record.section,
                "retrieval_quality": chunk_record.retrieval_quality,
                "chunk_index": chunk_record.chunk_index,
                "char_start": chunk_record.char_start,
                "char_end": chunk_record.char_end,
                "word_count": chunk_record.word_count,
                "related_entities": chunk_record.related_entities,
            },
        )
        for chunk_record in chunk_records
    ]


def build_faiss_index(vector_documents: list[Document], embeddings: HuggingFaceEmbeddings) -> FAISS:
    return FAISS.from_documents(vector_documents, embeddings)


def save_chunk_manifest(chunk_records: list[ChunkRecord], path: Path) -> None:
    payload = "\n".join(json.dumps(asdict(chunk_record), ensure_ascii=False) for chunk_record in chunk_records)
    path.write_text(payload + "\n", encoding="utf-8")


def save_build_report(build_result: BuildResult, path: Path) -> None:
    path.write_text(json.dumps(asdict(build_result), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def save_index(index: FAISS, index_dir: Path, index_name: str = DEFAULT_INDEX_NAME) -> None:
    index.save_local(str(index_dir), index_name=index_name)


def load_index(
    index_dir: Path,
    embeddings: HuggingFaceEmbeddings,
    index_name: str = DEFAULT_INDEX_NAME,
) -> FAISS:
    return FAISS.load_local(
        str(index_dir),
        embeddings,
        index_name=index_name,
        allow_dangerous_deserialization=True,
    )


def measure_embedding_dimension(embeddings: HuggingFaceEmbeddings) -> int:
    return len(embeddings.embed_query("dimension probe"))


def run_preview_queries(index: FAISS, top_k: int) -> list[dict[str, Any]]:
    previews: list[dict[str, Any]] = []
    for query in DEFAULT_PREVIEW_QUERIES:
        previews.append(
            {
                "query": query,
                "matches": [asdict(match) for match in search_index(index, query, top_k)],
            }
        )
    return previews


def search_index(index: FAISS, query: str, top_k: int) -> list[QueryMatch]:
    matches: list[QueryMatch] = []
    for rank, (document, score) in enumerate(index.similarity_search_with_score(query, k=top_k), start=1):
        metadata = document.metadata
        matches.append(
            QueryMatch(
                rank=rank,
                score=float(score),
                chunk_id=str(metadata["chunk_id"]),
                source_path=str(metadata["source_path"]),
                title=str(metadata["title"]),
                section=str(metadata["section"]),
                excerpt=build_excerpt(strip_chunk_prefix(document.page_content)),
            )
        )
    return matches


def build_excerpt(text: str, limit: int = 220) -> str:
    compact_text = re.sub(r"\s+", " ", text).strip()
    if len(compact_text) <= limit:
        return compact_text
    return compact_text[: limit - 3].rstrip() + "..."


def strip_chunk_prefix(page_content: str) -> str:
    lines = page_content.splitlines()
    if len(lines) >= 5 and lines[0].startswith("Title: ") and lines[1].startswith("Type: ") and lines[2].startswith("Section: "):
        return "\n".join(lines[4:]).strip()
    return page_content.strip()


def build_index_artifacts(
    knowledge_base_dir: Path,
    output_dir: Path,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    top_k_preview: int = 3,
) -> BuildResult:
    runtime_dir = output_dir / "runtime_tmp"
    output_dir.mkdir(parents=True, exist_ok=True)
    prepare_runtime_environment(runtime_dir)

    try:
        build_started_at = time.perf_counter()
        knowledge_base_documents = load_knowledge_base_documents(knowledge_base_dir)
        splitter = create_text_splitter()
        chunk_records = build_chunk_records(knowledge_base_documents, splitter)
        embeddings = create_embeddings(model_name)
        embedding_dimension = measure_embedding_dimension(embeddings)
        vector_documents = build_vector_documents(chunk_records)
        index = build_faiss_index(vector_documents, embeddings)

        index_dir = output_dir / FAISS_INDEX_DIRNAME
        index_dir.mkdir(parents=True, exist_ok=True)
        save_index(index, index_dir)
        save_chunk_manifest(chunk_records, output_dir / "chunks.jsonl")

        build_seconds = round(time.perf_counter() - build_started_at, 3)
        build_result = BuildResult(
            embedding_model=model_name,
            embedding_model_url=DEFAULT_EMBEDDING_MODEL_URL,
            embedding_dimension=embedding_dimension,
            knowledge_base_dir=to_repo_relative_path(knowledge_base_dir),
            documents_count=len(knowledge_base_documents),
            chunks_count=len(chunk_records),
            chunking_strategy=(
                "Hybrid section-aware chunking: short sections kept intact; "
                "long sections split with RecursiveCharacterTextSplitter.from_tiktoken_encoder"
            ),
            chunk_size=DEFAULT_CHUNK_SIZE,
            chunk_overlap=DEFAULT_CHUNK_OVERLAP,
            build_seconds=build_seconds,
            created_at=datetime.now(timezone.utc).isoformat(),
            preview_queries=run_preview_queries(index, top_k_preview),
        )
        save_build_report(build_result, output_dir / "index_build_report.json")
        return build_result
    finally:
        cleanup_runtime_environment(runtime_dir)


def to_repo_relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()
