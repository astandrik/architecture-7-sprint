#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


REQUIRED_ANCHORS = {
    "Spira",
    "Sin",
    "Yevon",
    "Summoner",
    "summoner",
    "Aeon",
    "aeon",
    "Fayth",
    "Farplane",
    "Guardian",
    "guardian",
    "Maester",
    "maester",
    "Blitzball",
    "Al Bhed",
    "Guado",
    "Ronso",
    "Final Summoning",
    "Calm",
    "Cloister of Trials",
}

FORBIDDEN_MARKERS = {
    "final fantasy",
    "kingdom hearts",
    "dissidia",
    "hd remaster",
    "ultimania",
    "creature creator",
    "sphere grid",
    "celestial weapon",
    "overdrive",
    "dressphere",
    "sphere break",
    "fiend arena",
    "macalania",
    "kilika",
    "baaj",
    "remiem",
    "moonflow",
    "guadosalam",
    "djose",
    "bikanel",
    "gullwings",
    "paine",
    "shuyin",
    "anima",
    "yojimbo",
    "kogoro",
    "leblanc",
    "kinoc",
    "yo mika",
    "maechen",
    "chappu",
    "isaaru",
    "evrae",
    "via purifico",
    "vivi ornitier",
    "chocobo",
    "shoopuf",
    "travel agenc",
    "sphere hunter",
    "full-motion video",
    "in-game",
    "attack command",
    "item command",
    "special magical effects",
    "number of battles fought",
    " hp ",
    "japanese version",
    "english versions",
    "substitution cipher",
    "katakana",
    "hiragana",
    "kanji",
    "primer",
    "primers",
    "written dialogue",
    "translated automatically",
    "the city at the end of the world",
    "english/japanese",
    "games depict it",
    "during the game",
    "geneaux",
    "genais",
    "crimson blades",
    "crimson squad",
    "field options",
    "affection mechanics",
    "affection points",
    "love interest",
    "regular league season",
    "exhibition play",
    "tournament play",
    "golden goal",
    "overtime",
    "tourists away",
    "real-world latin alphabet",
    "english alphabet",
    "homage",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate the synthetic Final Fantasy X knowledge base.")
    parser.add_argument(
        "--manifest",
        default="Task2/source_manifest.json",
        help="Path to the manifest JSON file.",
    )
    parser.add_argument(
        "--terms-map",
        default="knowledge_base/terms_map.json",
        help="Path to the final terms map JSON file.",
    )
    parser.add_argument(
        "--kb-dir",
        default="knowledge_base",
        help="Path to the final knowledge base directory.",
    )
    return parser.parse_args()


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def assert_counts(manifest: list[dict[str, object]], kb_dir: Path) -> list[str]:
    markdown_files = sorted(kb_dir.glob("*.md"))
    errors: list[str] = []
    if len(manifest) != 32:
        errors.append(f"manifest count is {len(manifest)}, expected 32")
    if len(markdown_files) < 32:
        errors.append(f"knowledge base has {len(markdown_files)} markdown files, expected at least 32")
    if not (kb_dir / "terms_map.json").exists():
        errors.append("knowledge_base/terms_map.json is missing")
    return errors


def assert_mapping_coverage(
    manifest: list[dict[str, object]],
    terms_map: dict[str, str],
) -> list[str]:
    errors: list[str] = []
    for entry in manifest:
        source_title = str(entry["source_title"])
        if source_title not in terms_map:
            errors.append(f"terms_map.json is missing mapping for {source_title}")

    for anchor in sorted(REQUIRED_ANCHORS):
        if anchor not in terms_map:
            errors.append(f"terms_map.json is missing anchor mapping for {anchor}")
    return errors


def find_leaks(
    kb_dir: Path,
    manifest: list[dict[str, object]],
    terms_map: dict[str, str],
) -> list[str]:
    canonical_tokens = set(terms_map.keys())
    canonical_tokens.update(str(entry["source_title"]) for entry in manifest)
    leaks: list[str] = []

    for markdown_path in sorted(kb_dir.glob("*.md")):
        content = markdown_path.read_text(encoding="utf-8")
        scan_content = re.sub(r"^Type:\s+.+?$", "", content, count=1, flags=re.MULTILINE)
        normalized_content = f" {scan_content.lower()} "
        if re.search(r"</?\w+", content):
            leaks.append(f"{markdown_path.name}: contains HTML-like markup")

        if len(content.strip()) < 300:
            leaks.append(f"{markdown_path.name}: content is unexpectedly short")

        for token in sorted(canonical_tokens, key=len, reverse=True):
            pattern = re.compile(rf"(?<!\w){re.escape(token)}(?!\w)")
            if pattern.search(scan_content):
                leaks.append(f"{markdown_path.name}: leaked token `{token}`")
                break

        for marker in sorted(FORBIDDEN_MARKERS):
            if marker in normalized_content:
                leaks.append(f"{markdown_path.name}: leaked marker `{marker}`")
                break

    return leaks


def main() -> int:
    args = parse_args()
    manifest = load_json(Path(args.manifest))
    if not isinstance(manifest, list):
        raise ValueError("manifest must be a JSON array")

    terms_map = load_json(Path(args.terms_map))
    if not isinstance(terms_map, dict):
        raise ValueError("terms map must be a JSON object")

    kb_dir = Path(args.kb_dir)

    errors = []
    errors.extend(assert_counts(manifest, kb_dir))
    errors.extend(assert_mapping_coverage(manifest, terms_map))
    errors.extend(find_leaks(kb_dir, manifest, terms_map))

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    print("Task 2 knowledge base validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
