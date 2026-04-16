#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from task3_indexing import BuildResult, Task3ValidationError, build_index_artifacts, parse_knowledge_base_document  # noqa: E402


DEFAULT_STATE_PATH = "artifacts/task6/update_state.json"
DEFAULT_LOG_PATH = "artifacts/task6/update_log.jsonl"
SUCCESS_STATUS = "success"
NO_CHANGES_STATUS = "no_changes"
PARTIAL_FAILURE_STATUS = "partial_failure"
FAILED_STATUS = "failed"
VALID_STATUSES = {
    SUCCESS_STATUS,
    NO_CHANGES_STATUS,
    PARTIAL_FAILURE_STATUS,
    FAILED_STATUS,
}
TERMS_MAP_FILENAME = "terms_map.json"
MARKDOWN_GLOB = "*.md"


@dataclass(frozen=True)
class SourceFileSnapshot:
    relative_path: str
    sha256: str
    size_bytes: int
    synced_to: str
    last_seen_at: str


@dataclass(frozen=True)
class DiffResult:
    new_files: tuple[str, ...]
    changed_files: tuple[str, ...]
    deleted_files: tuple[str, ...]
    unchanged_files: tuple[str, ...]


@dataclass(frozen=True)
class UpdateRunResult:
    exit_code: int
    status: str
    rebuild_performed: bool
    log_path: Path
    log_entry: dict[str, Any]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update the Task 3 FAISS index from daily docs changes.")
    parser.add_argument(
        "--source-dir",
        default="docs",
        help="Directory with source markdown documents to ingest.",
    )
    parser.add_argument(
        "--kb-dir",
        default="knowledge_base",
        help="Working knowledge base directory used for indexing.",
    )
    parser.add_argument(
        "--index-output-dir",
        default="artifacts/task3",
        help="Directory where Task 3 index artifacts are stored.",
    )
    parser.add_argument(
        "--state-path",
        default=DEFAULT_STATE_PATH,
        help="Path to the persistent update state JSON file.",
    )
    parser.add_argument(
        "--log-path",
        default=DEFAULT_LOG_PATH,
        help="Path to the append-only JSONL log file.",
    )
    return parser.parse_args()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def discover_source_files(source_dir: Path, kb_dir: Path, scanned_at: str) -> dict[str, SourceFileSnapshot]:
    snapshots: dict[str, SourceFileSnapshot] = {}
    for path in sorted(source_dir.glob(MARKDOWN_GLOB)):
        if not path.is_file():
            continue
        relative_path = path.relative_to(source_dir).as_posix()
        snapshots[relative_path] = SourceFileSnapshot(
            relative_path=relative_path,
            sha256=sha256_file(path),
            size_bytes=path.stat().st_size,
            synced_to=(kb_dir / relative_path).as_posix(),
            last_seen_at=scanned_at,
        )
    return snapshots


def load_state(state_path: Path) -> dict[str, Any]:
    if not state_path.exists():
        return {}
    return json.loads(state_path.read_text(encoding="utf-8"))


def extract_state_files(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    files = state.get("files", {})
    if not isinstance(files, dict):
        raise ValueError("update state must contain a `files` object.")
    return files


def diff_snapshots(
    previous_files: dict[str, dict[str, Any]],
    current_files: dict[str, SourceFileSnapshot],
) -> DiffResult:
    previous_paths = set(previous_files)
    current_paths = set(current_files)

    new_files = sorted(current_paths - previous_paths)
    deleted_files = sorted(previous_paths - current_paths)

    changed_files: list[str] = []
    unchanged_files: list[str] = []
    for relative_path in sorted(current_paths & previous_paths):
        previous_sha = str(previous_files[relative_path].get("sha256", ""))
        current_sha = current_files[relative_path].sha256
        if current_sha != previous_sha:
            changed_files.append(relative_path)
        else:
            unchanged_files.append(relative_path)

    return DiffResult(
        new_files=tuple(new_files),
        changed_files=tuple(changed_files),
        deleted_files=tuple(deleted_files),
        unchanged_files=tuple(unchanged_files),
    )


def validate_source_documents(
    source_dir: Path,
    relative_paths: list[str],
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for relative_path in relative_paths:
        candidate_path = source_dir / relative_path
        try:
            parse_knowledge_base_document(candidate_path)
        except (Task3ValidationError, UnicodeDecodeError, OSError, ValueError) as error:
            errors.append(f"{relative_path}: {error}")
    if not relative_paths:
        warnings.append("No new or changed markdown documents detected for validation.")
    return errors, warnings


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def sync_changes(
    source_dir: Path,
    kb_dir: Path,
    diff_result: DiffResult,
) -> None:
    kb_dir.mkdir(parents=True, exist_ok=True)
    for relative_path in diff_result.new_files + diff_result.changed_files:
        source_path = source_dir / relative_path
        target_path = kb_dir / relative_path
        ensure_parent_dir(target_path)
        shutil.copy2(source_path, target_path)

    for relative_path in diff_result.deleted_files:
        target_path = kb_dir / relative_path
        if target_path.exists():
            target_path.unlink()


def save_state(
    state_path: Path,
    source_dir: Path,
    kb_dir: Path,
    snapshots: dict[str, SourceFileSnapshot],
    last_successful_run_at: str,
) -> None:
    ensure_parent_dir(state_path)
    payload = {
        "source_dir": source_dir.as_posix(),
        "kb_dir": kb_dir.as_posix(),
        "last_successful_run_at": last_successful_run_at,
        "files": {
            relative_path: asdict(snapshot)
            for relative_path, snapshot in sorted(snapshots.items())
        },
    }
    state_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def count_index_size_bytes(index_output_dir: Path) -> int:
    total_size = 0
    for path in index_output_dir.rglob("*"):
        if path.is_file():
            total_size += path.stat().st_size
    return total_size


def build_log_entry(
    *,
    run_started_at: str,
    run_finished_at: str,
    status: str,
    source_dir: Path,
    kb_dir: Path,
    index_output_dir: Path,
    diff_result: DiffResult,
    files_scanned_count: int,
    documents_after_sync_count: int,
    chunks_after_rebuild_count: int | None,
    index_size_bytes: int | None,
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    if status not in VALID_STATUSES:
        raise ValueError(f"Unsupported status: {status}")

    return {
        "run_started_at": run_started_at,
        "run_finished_at": run_finished_at,
        "status": status,
        "source_dir": source_dir.as_posix(),
        "kb_dir": kb_dir.as_posix(),
        "index_output_dir": index_output_dir.as_posix(),
        "new_files_count": len(diff_result.new_files),
        "changed_files_count": len(diff_result.changed_files),
        "deleted_files_count": len(diff_result.deleted_files),
        "unchanged_files_count": len(diff_result.unchanged_files),
        "files_scanned_count": files_scanned_count,
        "documents_after_sync_count": documents_after_sync_count,
        "chunks_after_rebuild_count": chunks_after_rebuild_count,
        "index_size_bytes": index_size_bytes,
        "errors": errors,
        "warnings": warnings,
    }


def append_log_entry(log_path: Path, log_entry: dict[str, Any]) -> None:
    ensure_parent_dir(log_path)
    with log_path.open("a", encoding="utf-8") as file_obj:
        file_obj.write(json.dumps(log_entry, ensure_ascii=False) + "\n")


def build_run_summary(result: UpdateRunResult) -> str:
    log_entry = result.log_entry
    return (
        f"status={result.status} "
        f"new={log_entry['new_files_count']} "
        f"changed={log_entry['changed_files_count']} "
        f"deleted={log_entry['deleted_files_count']} "
        f"rebuild={result.rebuild_performed} "
        f"log={result.log_path}"
    )


def run_update(
    *,
    source_dir: Path,
    kb_dir: Path,
    index_output_dir: Path,
    state_path: Path,
    log_path: Path,
    build_index_fn: Callable[..., BuildResult] = build_index_artifacts,
) -> UpdateRunResult:
    run_started_at = utc_now_iso()
    errors: list[str] = []
    warnings: list[str] = []
    rebuild_performed = False
    chunks_after_rebuild_count: int | None = None
    index_size_bytes: int | None = None
    documents_after_sync_count = len(list(kb_dir.glob(MARKDOWN_GLOB))) if kb_dir.exists() else 0

    try:
        source_dir.mkdir(parents=True, exist_ok=True)
        scanned_at = utc_now_iso()
        previous_state = load_state(state_path)
        previous_files = extract_state_files(previous_state)
        current_snapshots = discover_source_files(source_dir, kb_dir, scanned_at)
        diff_result = diff_snapshots(previous_files, current_snapshots)

        files_to_validate = list(diff_result.new_files + diff_result.changed_files)
        validation_errors, validation_warnings = validate_source_documents(source_dir, files_to_validate)
        errors.extend(validation_errors)
        warnings.extend(validation_warnings)

        if errors:
            status = PARTIAL_FAILURE_STATUS
            run_finished_at = utc_now_iso()
            log_entry = build_log_entry(
                run_started_at=run_started_at,
                run_finished_at=run_finished_at,
                status=status,
                source_dir=source_dir,
                kb_dir=kb_dir,
                index_output_dir=index_output_dir,
                diff_result=diff_result,
                files_scanned_count=len(current_snapshots),
                documents_after_sync_count=documents_after_sync_count,
                chunks_after_rebuild_count=None,
                index_size_bytes=None,
                errors=errors,
                warnings=warnings,
            )
            append_log_entry(log_path, log_entry)
            return UpdateRunResult(exit_code=1, status=status, rebuild_performed=False, log_path=log_path, log_entry=log_entry)

        has_changes = bool(diff_result.new_files or diff_result.changed_files or diff_result.deleted_files)
        if has_changes:
            sync_changes(source_dir, kb_dir, diff_result)
            documents_after_sync_count = len(list(kb_dir.glob(MARKDOWN_GLOB)))
            build_result = build_index_fn(
                knowledge_base_dir=kb_dir,
                output_dir=index_output_dir,
                top_k_preview=3,
            )
            rebuild_performed = True
            chunks_after_rebuild_count = build_result.chunks_count
            index_size_bytes = count_index_size_bytes(index_output_dir)
            save_state(
                state_path=state_path,
                source_dir=source_dir,
                kb_dir=kb_dir,
                snapshots=current_snapshots,
                last_successful_run_at=utc_now_iso(),
            )
            status = SUCCESS_STATUS
        else:
            status = NO_CHANGES_STATUS
            warnings = ["No changes detected in source documents."]

        run_finished_at = utc_now_iso()
        log_entry = build_log_entry(
            run_started_at=run_started_at,
            run_finished_at=run_finished_at,
            status=status,
            source_dir=source_dir,
            kb_dir=kb_dir,
            index_output_dir=index_output_dir,
            diff_result=diff_result,
            files_scanned_count=len(current_snapshots),
            documents_after_sync_count=documents_after_sync_count,
            chunks_after_rebuild_count=chunks_after_rebuild_count,
            index_size_bytes=index_size_bytes,
            errors=errors,
            warnings=warnings,
        )
        append_log_entry(log_path, log_entry)
        return UpdateRunResult(
            exit_code=0,
            status=status,
            rebuild_performed=rebuild_performed,
            log_path=log_path,
            log_entry=log_entry,
        )
    except Exception as error:
        errors.append(str(error))
        run_finished_at = utc_now_iso()
        diff_result = DiffResult((), (), (), ())
        log_entry = build_log_entry(
            run_started_at=run_started_at,
            run_finished_at=run_finished_at,
            status=FAILED_STATUS,
            source_dir=source_dir,
            kb_dir=kb_dir,
            index_output_dir=index_output_dir,
            diff_result=diff_result,
            files_scanned_count=0,
            documents_after_sync_count=documents_after_sync_count,
            chunks_after_rebuild_count=None,
            index_size_bytes=None,
            errors=errors,
            warnings=warnings,
        )
        append_log_entry(log_path, log_entry)
        return UpdateRunResult(exit_code=1, status=FAILED_STATUS, rebuild_performed=False, log_path=log_path, log_entry=log_entry)


def main() -> int:
    args = parse_args()
    result = run_update(
        source_dir=REPO_ROOT / args.source_dir,
        kb_dir=REPO_ROOT / args.kb_dir,
        index_output_dir=REPO_ROOT / args.index_output_dir,
        state_path=REPO_ROOT / args.state_path,
        log_path=REPO_ROOT / args.log_path,
    )
    print(build_run_summary(result))
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
