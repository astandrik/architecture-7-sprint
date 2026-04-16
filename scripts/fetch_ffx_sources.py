#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import quote, unquote, urlparse

import requests
from bs4 import BeautifulSoup, NavigableString, Tag


USER_AGENT = (
    "Mozilla/5.0 (compatible; ArchitectureSprintBot/1.0; "
    "+https://github.com/astandrik/architecture-7-sprint)"
)

STOP_SECTION_TITLES = {
    "behind the scenes information",
    "behind the scenes",
    "other appearances",
    "gallery",
    "trivia",
    "references",
    "citations",
    "etymology",
    "other media",
    "non-final fantasy guest appearances",
}

SKIP_SECTION_TITLES = {
    "see also",
    "navigation",
    "related pages",
    "external links",
}

BLOCK_TAGS = {"p", "ul", "ol"}


@dataclass(frozen=True)
class ManifestEntry:
    source_url: str
    source_title: str
    entity_type: str
    synthetic_title: str
    synthetic_slug: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch and clean Final Fantasy X wiki pages.")
    parser.add_argument(
        "--manifest",
        default="Task2/source_manifest.json",
        help="Path to the manifest JSON file.",
    )
    parser.add_argument(
        "--output-dir",
        default="artifacts/source_docs",
        help="Directory for cleaned source documents.",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=0.4,
        help="Delay between HTTP requests.",
    )
    return parser.parse_args()


def load_manifest(path: Path) -> list[ManifestEntry]:
    raw_entries = json.loads(path.read_text(encoding="utf-8"))
    return [ManifestEntry(**entry) for entry in raw_entries]


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def fandom_api_url(source_url: str) -> str:
    parsed_url = urlparse(source_url)
    page_slug = unquote(parsed_url.path.removeprefix("/wiki/"))
    page_param = quote(page_slug, safe="()_")
    return (
        f"{parsed_url.scheme}://{parsed_url.netloc}/api.php"
        f"?action=parse&page={page_param}&redirects=1&prop=text&formatversion=2&format=json"
    )


def fetch_html(session: requests.Session, url: str) -> str:
    api_url = fandom_api_url(url)
    response = session.get(api_url, timeout=30)
    response.raise_for_status()
    payload = response.json()
    parse_block = payload.get("parse")
    if not isinstance(parse_block, dict) or "text" not in parse_block:
        raise ValueError(f"Fandom parse API returned an unexpected payload for {url}.")
    return str(parse_block["text"])


def extract_article_root(soup: BeautifulSoup) -> Tag:
    article_root = soup.select_one("div.mw-parser-output")
    if article_root is None:
        raise ValueError("Could not find article body with selector div.mw-parser-output.")
    return article_root


def prune_noise(root: Tag) -> None:
    selectors = [
        "aside",
        "table",
        "figure",
        "script",
        "style",
        "sup.reference",
        ".portable-infobox",
        ".navbox",
        ".toc",
        ".mw-editsection",
        ".noprint",
        ".license-description",
        ".quote",
        ".gallery",
    ]
    for selector in selectors:
        for node in root.select(selector):
            node.decompose()


def normalize_text(text: str) -> str:
    compact = re.sub(r"\[[^\]]+\]", " ", text)
    compact = compact.replace("\xa0", " ")
    compact = re.sub(r"\s+", " ", compact)
    return compact.strip()


def heading_text(tag: Tag) -> str:
    text = " ".join(tag.stripped_strings)
    return normalize_text(text).lower()


def iter_direct_tags(root: Tag) -> Iterable[Tag]:
    for child in root.children:
        if isinstance(child, Tag):
            yield child
        elif isinstance(child, NavigableString):
            continue


def extract_blocks(root: Tag) -> list[str]:
    blocks: list[str] = []
    current_section = "overview"

    for tag in iter_direct_tags(root):
        if tag.name in {"h2", "h3"}:
            normalized_heading = heading_text(tag)
            if normalized_heading in STOP_SECTION_TITLES:
                break
            if normalized_heading in SKIP_SECTION_TITLES:
                current_section = normalized_heading
                continue
            current_section = normalized_heading
            continue

        if current_section in SKIP_SECTION_TITLES or tag.name not in BLOCK_TAGS:
            continue

        if tag.name == "p":
            paragraph = normalize_text(tag.get_text(" ", strip=True))
            if len(paragraph) < 60:
                continue
            blocks.append(paragraph)
            continue

        for item in tag.find_all("li", recursive=False):
            bullet = normalize_text(item.get_text(" ", strip=True))
            if len(bullet) < 40:
                continue
            blocks.append(bullet)

    return blocks[:18]


def fallback_summary(soup: BeautifulSoup) -> list[str]:
    description = soup.find("meta", attrs={"property": "og:description"})
    if description is None:
        return []

    content = normalize_text(description.get("content", ""))
    return [content] if content else []


def build_payload(entry: ManifestEntry, blocks: list[str]) -> dict[str, object]:
    overview = blocks[:2]
    details = blocks[2:]
    if not overview and blocks:
        overview = [blocks[0]]
    if not details and len(blocks) > 1:
        details = blocks[1:]

    plain_text = "\n\n".join(blocks)
    return {
        "source_title": entry.source_title,
        "source_url": entry.source_url,
        "entity_type": entry.entity_type,
        "synthetic_title": entry.synthetic_title,
        "synthetic_slug": entry.synthetic_slug,
        "overview_blocks": overview,
        "detail_blocks": details,
        "plain_text": plain_text,
    }


def write_payload(output_dir: Path, payload: dict[str, object]) -> None:
    output_path = output_dir / f"{payload['synthetic_slug']}.json"
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def fetch_entry(
    session: requests.Session,
    output_dir: Path,
    entry: ManifestEntry,
    delay_seconds: float,
) -> None:
    html = fetch_html(session, entry.source_url)
    soup = BeautifulSoup(html, "lxml")
    article_root = extract_article_root(soup)
    prune_noise(article_root)
    blocks = extract_blocks(article_root)
    if not blocks:
        blocks = fallback_summary(soup)

    if not blocks:
        raise ValueError(f"No usable text blocks extracted for {entry.source_title}.")

    payload = build_payload(entry, blocks)
    write_payload(output_dir, payload)
    time.sleep(delay_seconds)


def main() -> int:
    args = parse_args()
    manifest_path = Path(args.manifest)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    entries = load_manifest(manifest_path)
    session = build_session()

    failures: list[str] = []
    for entry in entries:
        try:
            fetch_entry(session, output_dir, entry, args.delay_seconds)
            print(f"fetched {entry.source_title}")
        except Exception as error:  # noqa: BLE001
            failures.append(f"{entry.source_title}: {error}")
            print(f"failed {entry.source_title}: {error}", file=sys.stderr)

    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
