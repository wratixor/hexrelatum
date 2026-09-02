#!/usr/bin/env python3
"""Build Hexrelatum's deterministic public graph indexes.

SPDX-License-Identifier: AGPL-3.0-or-later
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit


FORMAT_VERSION = "0.2"
PROJECTION_VERSION = "paired-balance-preview-v0"
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
LINK_PATTERN = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)")
ALLOWED_FIELDS = {"id", "title", "coordinates", "home", "map"}
AXIS_LABEL_MAX_LENGTH = 32


class IndexBuildError(ValueError):
    """Raised when wiki source cannot produce a valid index."""


@dataclass(frozen=True)
class Article:
    id: str
    title: str
    coordinates: tuple[float, float, float, float, float, float]
    home: bool
    map_first: bool
    path: Path
    body: str


def load_axes(repository_root: Path) -> tuple[str, list[dict[str, str]]]:
    path = repository_root / "wiki.config.json"
    configuration = json.loads(path.read_text(encoding="utf-8"))
    if set(configuration) != {"axisSemanticsVersion", "axes"}:
        raise IndexBuildError(f"{path}: expected only axisSemanticsVersion and axes")
    version = configuration["axisSemanticsVersion"]
    axes = configuration["axes"]
    if not isinstance(version, str) or not ID_PATTERN.fullmatch(version):
        raise IndexBuildError(f"{path}: axisSemanticsVersion must be a stable lowercase-hyphen id")
    if not isinstance(axes, list) or len(axes) != 3:
        raise IndexBuildError(f"{path}: axes must contain exactly three opposed pairs")
    validated: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for index, axis in enumerate(axes):
        if not isinstance(axis, dict) or set(axis) != {"id", "positive", "negative"}:
            raise IndexBuildError(f"{path}: axis {index} must contain id, positive and negative")
        axis_id = axis["id"]
        if not isinstance(axis_id, str) or not ID_PATTERN.fullmatch(axis_id) or axis_id in seen_ids:
            raise IndexBuildError(f"{path}: axis {index} has an invalid or duplicate id")
        seen_ids.add(axis_id)
        for pole in ("positive", "negative"):
            label = axis[pole]
            if not isinstance(label, str) or not label.strip() or len(label) > AXIS_LABEL_MAX_LENGTH:
                raise IndexBuildError(f"{path}: axis {index} {pole} must contain 1..{AXIS_LABEL_MAX_LENGTH} characters")
        validated.append({"id": axis_id, "positive": axis["positive"].strip(), "negative": axis["negative"].strip()})
    return version, validated


def parse_bool(raw: str, *, field: str, path: Path) -> bool:
    if raw == "true":
        return True
    if raw == "false":
        return False
    raise IndexBuildError(f"{path}: {field} must be true or false")


def parse_article(path: Path, wiki_root: Path) -> Article:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise IndexBuildError(f"{path}: missing opening metadata delimiter")

    try:
        closing = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration as exc:
        raise IndexBuildError(f"{path}: missing closing metadata delimiter") from exc

    metadata: dict[str, str] = {}
    for line_number, line in enumerate(lines[1:closing], 2):
        if not line.strip():
            continue
        key, separator, value = line.partition(":")
        key = key.strip()
        if not separator or not key or not value.strip():
            raise IndexBuildError(f"{path}:{line_number}: expected 'key: value'")
        if key in metadata:
            raise IndexBuildError(f"{path}:{line_number}: duplicate field {key!r}")
        metadata[key] = value.strip()

    unknown = set(metadata) - ALLOWED_FIELDS
    missing = {"id", "title", "coordinates"} - set(metadata)
    if unknown:
        raise IndexBuildError(f"{path}: unsupported metadata fields: {', '.join(sorted(unknown))}")
    if missing:
        raise IndexBuildError(f"{path}: missing metadata fields: {', '.join(sorted(missing))}")

    concept_id = metadata["id"]
    if not ID_PATTERN.fullmatch(concept_id):
        raise IndexBuildError(f"{path}: id must match {ID_PATTERN.pattern}")

    title = metadata["title"].strip()
    if not title or len(title) > 128:
        raise IndexBuildError(f"{path}: title must contain 1..128 characters")

    try:
        coordinates_value = json.loads(metadata["coordinates"])
    except json.JSONDecodeError as exc:
        raise IndexBuildError(f"{path}: coordinates must be a JSON array") from exc
    if not isinstance(coordinates_value, list) or len(coordinates_value) != 6:
        raise IndexBuildError(f"{path}: coordinates must contain exactly six numbers")
    coordinates: list[float] = []
    for value in coordinates_value:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise IndexBuildError(f"{path}: every coordinate must be a number")
        number = float(value)
        if not math.isfinite(number) or number < 1:
            raise IndexBuildError(f"{path}: every coordinate must be finite and at least 1")
        coordinates.append(number)

    body = "\n".join(lines[closing + 1 :]).strip() + "\n"
    relative_path = path.relative_to(wiki_root)
    return Article(
        id=concept_id,
        title=title,
        coordinates=tuple(coordinates),  # type: ignore[arg-type]
        home=parse_bool(metadata.get("home", "false"), field="home", path=path),
        map_first=parse_bool(metadata.get("map", "false"), field="map", path=path),
        path=relative_path,
        body=body,
    )


def normalize_internal_target(article: Article, href: str, wiki_root: Path) -> Path | None:
    parsed = urlsplit(href)
    if parsed.scheme or parsed.netloc:
        return None
    if not parsed.path:
        return None
    decoded = unquote(parsed.path)
    candidate = (wiki_root / article.path.parent / decoded).resolve()
    wiki_resolved = wiki_root.resolve()
    if candidate != wiki_resolved and wiki_resolved not in candidate.parents:
        raise IndexBuildError(f"wiki/{article.path}: link escapes wiki/: {href}")
    return candidate.relative_to(wiki_resolved)


def collect_articles(wiki_root: Path) -> tuple[list[Article], dict[Path, Article]]:
    articles = [parse_article(path, wiki_root) for path in sorted(wiki_root.rglob("*.md"))]
    if not articles:
        raise IndexBuildError("wiki/ contains no Markdown articles")

    by_id: dict[str, Article] = {}
    by_path: dict[Path, Article] = {}
    for article in articles:
        if article.id in by_id:
            raise IndexBuildError(f"duplicate concept id: {article.id}")
        by_id[article.id] = article
        by_path[article.path] = article

    homes = [article for article in articles if article.home]
    if len(homes) != 1:
        raise IndexBuildError(f"expected exactly one home article, found {len(homes)}")
    return articles, by_path


def build_payload(repository_root: Path) -> tuple[dict[str, object], list[tuple[str, str, str, str]], list[tuple[str, str, str]]]:
    wiki_root = repository_root / "wiki"
    articles, by_path = collect_articles(wiki_root)
    by_id = {article.id: article for article in articles}

    directed_links: set[tuple[str, str, str, str]] = set()
    external_links: set[tuple[str, str, str]] = set()
    outgoing: dict[str, set[str]] = {article.id: set() for article in articles}
    incoming: dict[str, set[str]] = {article.id: set() for article in articles}

    for article in articles:
        for label, raw_href in LINK_PATTERN.findall(article.body):
            href = raw_href.strip()
            parsed = urlsplit(href)
            target_path = normalize_internal_target(article, href, wiki_root)
            if target_path is None:
                if parsed.scheme in {"http", "https"} and parsed.netloc:
                    external_links.add((article.id, label.strip(), href))
                continue
            target = by_path.get(target_path)
            if target is None:
                raise IndexBuildError(f"wiki/{article.path}: missing linked article: {href}")
            if target.id == article.id:
                continue
            outgoing[article.id].add(target.id)
            incoming[target.id].add(article.id)
            directed_links.add((article.id, target.id, label.strip(), href))

    provenance = json.loads((repository_root / "provenance.json").read_text(encoding="utf-8"))
    engine_version = (repository_root / "VERSION").read_text(encoding="utf-8").strip()
    axis_semantics_version, axes = load_axes(repository_root)
    home_id = next(article.id for article in articles if article.home)

    concepts: list[dict[str, object]] = []
    for article in sorted(articles, key=lambda item: item.id):
        linked_ids = sorted((outgoing[article.id] | incoming[article.id]) - {article.id})
        article_external = [
            {"label": label, "href": href}
            for source_id, label, href in sorted(external_links)
            if source_id == article.id
        ]
        concepts.append(
            {
                "id": article.id,
                "title": article.title,
                "path": f"wiki/{article.path.as_posix()}",
                "coordinates": list(article.coordinates),
                "body": article.body,
                "home": article.home,
                "map": article.map_first,
                "incomingCount": len(incoming[article.id]),
                "outgoingIds": sorted(outgoing[article.id]),
                "linkedIds": linked_ids,
                "externalLinks": article_external,
            }
        )

    payload: dict[str, object] = {
        "formatVersion": FORMAT_VERSION,
        "engineVersion": engine_version,
        "projection": PROJECTION_VERSION,
        "axisSemanticsVersion": axis_semantics_version,
        "axes": axes,
        "homeId": home_id,
        "provenance": provenance,
        "concepts": concepts,
    }
    return payload, sorted(directed_links), sorted(external_links)


def write_json(payload: dict[str, object], path: Path) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_sqlite(
    payload: dict[str, object],
    directed_links: list[tuple[str, str, str, str]],
    external_links: list[tuple[str, str, str]],
    path: Path,
) -> None:
    if path.exists():
        path.unlink()
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            PRAGMA application_id = 1212633164;
            PRAGMA user_version = 1;
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE concepts (
                id TEXT PRIMARY KEY,
                path TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                home INTEGER NOT NULL CHECK (home IN (0, 1)),
                map INTEGER NOT NULL CHECK (map IN (0, 1)),
                incoming_count INTEGER NOT NULL CHECK (incoming_count >= 0),
                c0 REAL NOT NULL CHECK (c0 >= 1),
                c1 REAL NOT NULL CHECK (c1 >= 1),
                c2 REAL NOT NULL CHECK (c2 >= 1),
                c3 REAL NOT NULL CHECK (c3 >= 1),
                c4 REAL NOT NULL CHECK (c4 >= 1),
                c5 REAL NOT NULL CHECK (c5 >= 1)
            );
            CREATE TABLE links (
                source_id TEXT NOT NULL REFERENCES concepts(id),
                target_id TEXT NOT NULL REFERENCES concepts(id),
                label TEXT NOT NULL,
                href TEXT NOT NULL,
                PRIMARY KEY (source_id, target_id, href)
            );
            CREATE TABLE external_links (
                source_id TEXT NOT NULL REFERENCES concepts(id),
                label TEXT NOT NULL,
                href TEXT NOT NULL,
                PRIMARY KEY (source_id, href)
            );
            """
        )
        metadata = {
            "formatVersion": str(payload["formatVersion"]),
            "engineVersion": str(payload["engineVersion"]),
            "projection": str(payload["projection"]),
            "axisSemanticsVersion": str(payload["axisSemanticsVersion"]),
            "axes": json.dumps(payload["axes"], ensure_ascii=False, sort_keys=True),
            "homeId": str(payload["homeId"]),
            "provenance": json.dumps(payload["provenance"], ensure_ascii=False, sort_keys=True),
        }
        connection.executemany(
            "INSERT INTO metadata(key, value) VALUES (?, ?)", sorted(metadata.items())
        )
        for concept in payload["concepts"]:  # type: ignore[assignment]
            coordinates = concept["coordinates"]
            connection.execute(
                """INSERT INTO concepts(
                    id, path, title, body, home, map, incoming_count,
                    c0, c1, c2, c3, c4, c5
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    concept["id"], concept["path"], concept["title"], concept["body"],
                    int(concept["home"]), int(concept["map"]), concept["incomingCount"],
                    *coordinates,
                ),
            )
        connection.executemany(
            "INSERT INTO links(source_id, target_id, label, href) VALUES (?, ?, ?, ?)",
            directed_links,
        )
        connection.executemany(
            "INSERT INTO external_links(source_id, label, href) VALUES (?, ?, ?)",
            external_links,
        )
        connection.commit()
        connection.execute("VACUUM")
    finally:
        connection.close()


def build(repository_root: Path, output_dir: Path) -> None:
    payload, directed_links, external_links = build_payload(repository_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(payload, output_dir / "index.json")
    write_sqlite(payload, directed_links, external_links, output_dir / "index.sqlite3")


def sqlite_dump(path: Path) -> str:
    connection = sqlite3.connect(path)
    try:
        return "\n".join(connection.iterdump())
    finally:
        connection.close()


def check(repository_root: Path, output_dir: Path) -> None:
    expected_json = output_dir / "index.json"
    expected_sqlite = output_dir / "index.sqlite3"
    if not expected_json.exists() or not expected_sqlite.exists():
        raise IndexBuildError("generated indexes are missing; run tools/build_index.py")
    with tempfile.TemporaryDirectory(prefix="hexrelatum-index-") as temporary:
        rebuilt = Path(temporary)
        build(repository_root, rebuilt)
        if rebuilt.joinpath("index.json").read_bytes() != expected_json.read_bytes():
            raise IndexBuildError("public/index.json is stale; rebuild and commit it")
        if sqlite_dump(rebuilt / "index.sqlite3") != sqlite_dump(expected_sqlite):
            raise IndexBuildError("public/index.sqlite3 is stale; rebuild and commit it")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify committed indexes")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    repository_root = Path(__file__).resolve().parents[1]
    output_dir = repository_root / "public"
    try:
        if args.check:
            check(repository_root, output_dir)
        else:
            build(repository_root, output_dir)
    except (IndexBuildError, OSError, sqlite3.Error, json.JSONDecodeError) as exc:
        print(f"index build failed: {exc}", file=sys.stderr)
        return 1
    action = "verified" if args.check else "built"
    print(f"Hexrelatum indexes {action}: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
