from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from build_synthetic_kb import is_meta_block, replace_terms  # noqa: E402
from validate_task2_kb import find_leaks  # noqa: E402


class Task2KbPipelineTests(unittest.TestCase):
    def test_replace_terms_cleans_common_replacement_artifacts(self) -> None:
        terms_map = {
            "Tidus": "Caelan Veyr",
            "Rikku": "Nerys Quill",
            "Al Bhed": "The Relicborn",
            "guardian": "oathsworn",
        }
        source_text = (
            "Tidus' father trusted a guardian. "
            "He respected a guardian from the order. "
            "Rikku carried her half- Al Bhed heritage proudly."
        )

        replaced = replace_terms(source_text, terms_map)

        self.assertIn("Caelan Veyr's father", replaced)
        self.assertIn("an oathsworn", replaced)
        self.assertIn("half-The Relicborn heritage", replaced)

    def test_is_meta_block_detects_residual_gameplay_and_reference_markers(self) -> None:
        self.assertTrue(
            is_meta_block(
                "Regardless of her role as a love interest, field options and affection mechanics raise affection points."
            )
        )
        self.assertTrue(
            is_meta_block(
                "The signs use the English alphabet and work like a real-world Latin alphabet cipher."
            )
        )
        self.assertFalse(
            is_meta_block(
                "Caelan Veyr crossed the ruined bridge and joined Elyra Noctis on the pilgrimage."
            )
        )

    def test_find_leaks_flags_newly_forbidden_markers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            kb_dir = Path(temp_dir)
            (kb_dir / "sample_affection.md").write_text(
                (
                    "# Sample Affection\n\n"
                    "Type: character\n\n"
                    "## Overview\n\n"
                    "This overview is intentionally long enough to avoid the short-content guard while still "
                    "mentioning love interest and affection mechanics as residual gameplay markers.\n\n"
                    "## Details\n\n"
                    "The remaining details stay narrative and should not affect the marker match.\n\n"
                    "## Related entities\n\n"
                    "- Example Entity\n"
                ),
                encoding="utf-8",
            )
            (kb_dir / "sample_alphabet.md").write_text(
                (
                    "# Sample Alphabet\n\n"
                    "Type: concept\n\n"
                    "## Overview\n\n"
                    "This overview is intentionally long enough to avoid the short-content guard while still "
                    "describing synthetic writing systems.\n\n"
                    "## Details\n\n"
                    "The signs work like a real-world Latin alphabet and explicitly mention the English alphabet "
                    "for debugging purposes in this synthetic document.\n\n"
                    "## Related entities\n\n"
                    "- Example Entity\n"
                ),
                encoding="utf-8",
            )

            leaks = find_leaks(
                kb_dir=kb_dir,
                manifest=[],
                terms_map={},
            )

            self.assertTrue(
                any(marker in leak for leak in leaks for marker in ("love interest", "affection mechanics"))
            )
            self.assertTrue(
                any(marker in leak for leak in leaks for marker in ("real-world latin alphabet", "english alphabet"))
            )


if __name__ == "__main__":
    unittest.main()
