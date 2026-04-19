from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
SRC_DIR = REPO_ROOT / "src"
for candidate in (SCRIPTS_DIR, SRC_DIR):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from task3_indexing import BuildResult  # noqa: E402
from update_index import (  # noqa: E402
    NO_CHANGES_STATUS,
    PARTIAL_FAILURE_STATUS,
    SUCCESS_STATUS,
    DiffResult,
    SourceFileSnapshot,
    build_log_entry,
    diff_snapshots,
    discover_source_files,
    load_state,
    run_update,
)


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
        created_at="2026-04-14T00:00:00+00:00",
        preview_queries=[],
    )


class UpdateIndexTests(unittest.TestCase):
    def test_diff_snapshots_classifies_new_changed_deleted_and_unchanged(self) -> None:
        current_files = {
            "new.md": SourceFileSnapshot(
                relative_path="new.md",
                sha256="new",
                size_bytes=10,
                synced_to="knowledge_base/new.md",
                last_seen_at="2026-04-14T00:00:00+00:00",
            ),
            "same.md": SourceFileSnapshot(
                relative_path="same.md",
                sha256="same",
                size_bytes=10,
                synced_to="knowledge_base/same.md",
                last_seen_at="2026-04-14T00:00:00+00:00",
            ),
            "changed.md": SourceFileSnapshot(
                relative_path="changed.md",
                sha256="changed-now",
                size_bytes=12,
                synced_to="knowledge_base/changed.md",
                last_seen_at="2026-04-14T00:00:00+00:00",
            ),
        }
        previous_files = {
            "same.md": {"sha256": "same"},
            "changed.md": {"sha256": "changed-before"},
            "deleted.md": {"sha256": "deleted"},
        }

        diff_result = diff_snapshots(previous_files, current_files)

        self.assertEqual(diff_result.new_files, ("new.md",))
        self.assertEqual(diff_result.changed_files, ("changed.md",))
        self.assertEqual(diff_result.deleted_files, ("deleted.md",))
        self.assertEqual(diff_result.unchanged_files, ("same.md",))

    def test_build_log_entry_contains_expected_counts(self) -> None:
        log_entry = build_log_entry(
            run_started_at="2026-04-14T00:00:00+00:00",
            run_finished_at="2026-04-14T00:01:00+00:00",
            status=SUCCESS_STATUS,
            source_dir=Path("docs"),
            kb_dir=Path("knowledge_base"),
            index_output_dir=Path("artifacts/task3"),
            diff_result=DiffResult(
                new_files=("new.md",),
                changed_files=("changed.md",),
                deleted_files=("deleted.md",),
                unchanged_files=("same.md",),
            ),
            files_scanned_count=3,
            documents_after_sync_count=4,
            chunks_after_rebuild_count=8,
            index_size_bytes=256,
            errors=[],
            warnings=[],
        )

        self.assertEqual(log_entry["new_files_count"], 1)
        self.assertEqual(log_entry["changed_files_count"], 1)
        self.assertEqual(log_entry["deleted_files_count"], 1)
        self.assertEqual(log_entry["unchanged_files_count"], 1)
        self.assertEqual(log_entry["files_scanned_count"], 3)
        self.assertEqual(log_entry["documents_after_sync_count"], 4)
        self.assertEqual(log_entry["chunks_after_rebuild_count"], 8)
        self.assertEqual(log_entry["index_size_bytes"], 256)

    def test_run_update_returns_no_changes_without_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "docs"
            kb_dir = root / "knowledge_base"
            index_dir = root / "artifacts" / "task3"
            state_path = root / "artifacts" / "task6" / "update_state.json"
            log_path = root / "artifacts" / "task6" / "update_log.jsonl"

            source_dir.mkdir(parents=True, exist_ok=True)
            kb_dir.mkdir(parents=True, exist_ok=True)
            write_markdown(source_dir / "alpha.md", "Alpha")
            snapshots = discover_source_files(source_dir, kb_dir, "2026-04-14T00:00:00+00:00")
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps(
                    {
                        "source_dir": source_dir.as_posix(),
                        "kb_dir": kb_dir.as_posix(),
                        "last_successful_run_at": "2026-04-14T00:00:00+00:00",
                        "files": {name: snapshot.__dict__ for name, snapshot in snapshots.items()},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            called = False

            def fake_build(**_: object) -> BuildResult:
                nonlocal called
                called = True
                return make_build_result(kb_dir)

            result = run_update(
                source_dir=source_dir,
                kb_dir=kb_dir,
                index_output_dir=index_dir,
                state_path=state_path,
                log_path=log_path,
                build_index_fn=fake_build,
            )

            self.assertEqual(result.exit_code, 0)
            self.assertEqual(result.status, NO_CHANGES_STATUS)
            self.assertFalse(result.rebuild_performed)
            self.assertFalse(called)
            self.assertEqual(result.log_entry["new_files_count"], 0)
            self.assertEqual(result.log_entry["changed_files_count"], 0)
            self.assertEqual(result.log_entry["deleted_files_count"], 0)

    def test_run_update_returns_partial_failure_for_invalid_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "docs"
            kb_dir = root / "knowledge_base"
            index_dir = root / "artifacts" / "task3"
            state_path = root / "artifacts" / "task6" / "update_state.json"
            log_path = root / "artifacts" / "task6" / "update_log.jsonl"

            source_dir.mkdir(parents=True, exist_ok=True)
            kb_dir.mkdir(parents=True, exist_ok=True)
            (source_dir / "broken.md").write_text("# Broken\n\nMissing schema\n", encoding="utf-8")

            result = run_update(
                source_dir=source_dir,
                kb_dir=kb_dir,
                index_output_dir=index_dir,
                state_path=state_path,
                log_path=log_path,
            )

            self.assertEqual(result.exit_code, 1)
            self.assertEqual(result.status, PARTIAL_FAILURE_STATUS)
            self.assertFalse(result.rebuild_performed)
            self.assertFalse(state_path.exists())
            self.assertFalse((kb_dir / "broken.md").exists())
            self.assertTrue(result.log_entry["errors"])

    def test_run_update_successfully_syncs_and_saves_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "docs"
            kb_dir = root / "knowledge_base"
            index_dir = root / "artifacts" / "task3"
            state_path = root / "artifacts" / "task6" / "update_state.json"
            log_path = root / "artifacts" / "task6" / "update_log.jsonl"

            source_dir.mkdir(parents=True, exist_ok=True)
            kb_dir.mkdir(parents=True, exist_ok=True)
            write_markdown(source_dir / "alpha.md", "Alpha")

            def fake_build(**_: object) -> BuildResult:
                index_dir.mkdir(parents=True, exist_ok=True)
                (index_dir / "stub.index").write_text("index", encoding="utf-8")
                return make_build_result(kb_dir)

            result = run_update(
                source_dir=source_dir,
                kb_dir=kb_dir,
                index_output_dir=index_dir,
                state_path=state_path,
                log_path=log_path,
                build_index_fn=fake_build,
            )

            self.assertEqual(result.exit_code, 0)
            self.assertEqual(result.status, SUCCESS_STATUS)
            self.assertTrue(result.rebuild_performed)
            self.assertTrue((kb_dir / "alpha.md").exists())
            self.assertTrue(state_path.exists())
            self.assertEqual(load_state(state_path)["files"]["alpha.md"]["synced_to"], (kb_dir / "alpha.md").as_posix())
            self.assertEqual(result.log_entry["new_files_count"], 1)
            self.assertEqual(result.log_entry["documents_after_sync_count"], 1)

    def test_run_update_deletes_previously_tracked_document(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "docs"
            kb_dir = root / "knowledge_base"
            index_dir = root / "artifacts" / "task3"
            state_path = root / "artifacts" / "task6" / "update_state.json"
            log_path = root / "artifacts" / "task6" / "update_log.jsonl"

            source_dir.mkdir(parents=True, exist_ok=True)
            kb_dir.mkdir(parents=True, exist_ok=True)
            write_markdown(kb_dir / "alpha.md", "Alpha")
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps(
                    {
                        "source_dir": source_dir.as_posix(),
                        "kb_dir": kb_dir.as_posix(),
                        "last_successful_run_at": "2026-04-14T00:00:00+00:00",
                        "files": {
                            "alpha.md": {
                                "sha256": "old",
                                "size_bytes": 10,
                                "synced_to": (kb_dir / "alpha.md").as_posix(),
                                "last_seen_at": "2026-04-14T00:00:00+00:00",
                            }
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            def fake_build(**_: object) -> BuildResult:
                index_dir.mkdir(parents=True, exist_ok=True)
                (index_dir / "stub.index").write_text("index", encoding="utf-8")
                return make_build_result(kb_dir)

            result = run_update(
                source_dir=source_dir,
                kb_dir=kb_dir,
                index_output_dir=index_dir,
                state_path=state_path,
                log_path=log_path,
                build_index_fn=fake_build,
            )

            self.assertEqual(result.exit_code, 0)
            self.assertEqual(result.status, SUCCESS_STATUS)
            self.assertFalse((kb_dir / "alpha.md").exists())
            self.assertEqual(result.log_entry["deleted_files_count"], 1)


if __name__ == "__main__":
    unittest.main()
