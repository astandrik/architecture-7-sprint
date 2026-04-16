#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path


META_MARKERS = {
    "final fantasy",
    "kingdom hearts",
    "dissidia",
    "hd remaster",
    "international version",
    "international and hd remaster",
    "pal version",
    "ultimania",
    "voice actor",
    "motion capture",
    "creature creator",
    "sphere grid",
    "celestial weapon",
    "overdrive",
    "dressphere",
    "dresspheres",
    "sphere break",
    "commsphere",
    "fiend arena",
    "new game plus",
    "trophies",
    "achievement",
    "soundtrack",
    "album",
    "sung by",
    "theme",
    "arranged",
    "developer",
    "gameplay",
    "boss",
    "minigame",
    "full-motion video",
    "official figurine",
    "special magical effects",
    "number of battles fought",
    "items in specific quantities",
    "using items",
    "travel agencies",
    "sphere hunter",
    "sphere hunters",
    "main story",
    "victory pose",
    "battle stance",
    "headquarters:",
    "opera omnia",
    "theatrhythm",
    "world of final fantasy",
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

RESIDUAL_WORLD_MARKERS = {
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
    "brotherhood",
    "nirvana",
    "caladbolg",
    "masamune",
    "spirit lance",
    "world champion",
    "cid",
    "belgemine",
    "isaaru",
    "evrae",
    "via purifico",
    "vivi ornitier",
    "machina war",
    "chocobo",
    "shoopuf",
    "psyches",
    "named brother",
    "vegnagun",
    "demonolith",
    "mi'ihen",
    "gui",
    "geneaux",
    "genais",
    "crimson blades",
    "crimson squad",
}


@dataclass(frozen=True)
class ManifestEntry:
    source_url: str
    source_title: str
    entity_type: str
    synthetic_title: str
    synthetic_slug: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the synthetic Final Fantasy X knowledge base.")
    parser.add_argument(
        "--manifest",
        default="Task2/source_manifest.json",
        help="Path to the manifest JSON file.",
    )
    parser.add_argument(
        "--terms-map",
        default="Task2/terms_map.json",
        help="Path to the terms map JSON file.",
    )
    parser.add_argument(
        "--source-dir",
        default="artifacts/source_docs",
        help="Directory with cleaned source JSON files.",
    )
    parser.add_argument(
        "--output-dir",
        default="knowledge_base",
        help="Directory for the final synthetic markdown files.",
    )
    return parser.parse_args()


def load_manifest(path: Path) -> list[ManifestEntry]:
    raw_entries = json.loads(path.read_text(encoding="utf-8"))
    return [ManifestEntry(**entry) for entry in raw_entries]


def load_terms_map(path: Path) -> dict[str, str]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_payload(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def replace_terms(text: str, terms_map: dict[str, str]) -> str:
    updated = text
    for original in sorted(terms_map, key=len, reverse=True):
        replacement = terms_map[original]
        pattern = re.compile(rf"(?<!\w){re.escape(original)}(?!\w)")
        updated = pattern.sub(replacement, updated)

    updated = re.sub(r"\s+", " ", updated)
    updated = re.sub(r"\s+([,.;:?!])", r"\1", updated)
    updated = re.sub(
        r"\b([Aa])\s+(?=(invoker|eidolon|Eclipseborn|oathsworn)\b)",
        lambda match: "an " if match.group(1).islower() else "An ",
        updated,
    )
    updated = re.sub(r"\bthe\s+The\b", "the", updated)
    updated = re.sub(r"\bThe\s+The\b", "The", updated)
    updated = re.sub(r"([^sS])'\s+(?=[A-Za-z])", r"\1's ", updated)
    updated = re.sub(r"\bhalf-\s+(?=[A-Z])", "half-", updated)
    updated = updated.replace(" 's", "'s")
    return updated.strip()


def find_related_entities(
    source_text: str,
    current_entry: ManifestEntry,
    manifest_entries: list[ManifestEntry],
) -> list[str]:
    related_titles: list[str] = []
    for candidate in manifest_entries:
        if candidate.source_title == current_entry.source_title:
            continue
        pattern = re.compile(rf"(?<!\w){re.escape(candidate.source_title)}(?!\w)")
        if pattern.search(source_text):
            related_titles.append(candidate.synthetic_title)

    return related_titles[:8]


def ensure_block_text(blocks: list[str], fallback: str) -> list[str]:
    cleaned_blocks = [block.strip() for block in blocks if block.strip()]
    return cleaned_blocks if cleaned_blocks else [fallback]


def fallback_entity_label(entity_type: str) -> str:
    return "summoned entity" if entity_type == "aeon" else entity_type


def is_meta_block(block: str) -> bool:
    normalized = block.lower()
    if any(marker in normalized for marker in META_MARKERS):
        return True
    if any(marker in normalized for marker in RESIDUAL_WORLD_MARKERS):
        return True
    if re.search(r"\b(hp|mp|agility|evasion|defense|strength|magic defense|attack command|stat growth)\b", normalized):
        return True
    if re.search(r"\b(haste|protect|reflect|regen|shell|nulblaze|nulfrost|nulshock|nultide)\b", normalized):
        return True
    if re.search(r"\b(real-world|english alphabet|latin alphabet|love interest|affection|field options?)\b", normalized):
        return True
    if re.search(r"\b(league season|exhibition play|tournament play|overtime|golden goal)\b", normalized):
        return True
    if re.search(r"\b(tourists away|homage)\b", normalized):
        return True
    if "/new " in normalized:
        return True
    if normalized.startswith("objective:") or normalized.startswith("unlock:"):
        return True
    if "player" in normalized and "pilgrimage" not in normalized:
        return True
    return False


def sanitize_blocks(raw_blocks: list[str], terms_map: dict[str, str], limit: int) -> list[str]:
    sanitized: list[str] = []
    for block in raw_blocks:
        if is_meta_block(block):
            continue
        replaced = replace_terms(block, terms_map)
        if is_meta_block(replaced):
            continue
        sanitized.append(replaced)
        if len(sanitized) >= limit:
            break
    return sanitized


def format_markdown(
    entry: ManifestEntry,
    overview_blocks: list[str],
    detail_blocks: list[str],
    related_entities: list[str],
) -> str:
    related_lines = related_entities or ["No explicit linked entities were identified in the cleaned source."]
    overview = "\n\n".join(f"- {block}" if block.startswith("See also:") else block for block in overview_blocks)
    details = "\n\n".join(f"- {block}" if block.startswith("See also:") else block for block in detail_blocks)
    related = "\n".join(f"- {title}" for title in related_lines)
    return (
        f"# {entry.synthetic_title}\n\n"
        f"Type: {entry.entity_type}\n\n"
        f"## Overview\n\n{overview}\n\n"
        f"## Details\n\n{details}\n\n"
        f"## Related entities\n\n{related}\n"
    )


def write_markdown(path: Path, content: str) -> None:
    path.write_text(content.strip() + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    manifest_path = Path(args.manifest)
    terms_map_path = Path(args.terms_map)
    source_dir = Path(args.source_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest_entries = load_manifest(manifest_path)
    terms_map = load_terms_map(terms_map_path)

    for entry in manifest_entries:
        payload_path = source_dir / f"{entry.synthetic_slug}.json"
        payload = load_payload(payload_path)
        plain_text = str(payload["plain_text"])
        overview_blocks = sanitize_blocks(list(payload["overview_blocks"]), terms_map, limit=2)
        detail_blocks = sanitize_blocks(list(payload["detail_blocks"]), terms_map, limit=4)

        overview_blocks = ensure_block_text(
            overview_blocks,
            (
                f"{entry.synthetic_title} is preserved in the archive as a "
                f"{fallback_entity_label(entry.entity_type)} woven into Elyndran history, ritual memory, "
                f"and the synthetic world model prepared for retrieval."
            ),
        )
        detail_blocks = ensure_block_text(
            detail_blocks,
            (
                f"Recovered notes about {entry.synthetic_title} remain fragmentary, yet the surviving records "
                f"still connect it to Elyndran institutions, pilgrimage-era practices, and a broader network "
                f"of related entities inside the synthetic corpus."
            ),
        )

        related_entities = find_related_entities(plain_text, entry, manifest_entries)
        markdown = format_markdown(entry, overview_blocks, detail_blocks, related_entities)
        write_markdown(output_dir / f"{entry.synthetic_slug}.md", markdown)

    terms_map_output = output_dir / "terms_map.json"
    terms_map_output.write_text(
        json.dumps(terms_map, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
