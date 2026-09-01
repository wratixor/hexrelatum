"""Tests for the Hexrelatum reference indexer.

SPDX-License-Identifier: AGPL-3.0-or-later
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "hexrelatum_build_index", REPOSITORY_ROOT / "tools" / "build_index.py"
)
assert SPEC and SPEC.loader
build_index = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = build_index
SPEC.loader.exec_module(build_index)


class BuildIndexTests(unittest.TestCase):
    def test_repository_wiki_builds_both_formats(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            build_index.build(REPOSITORY_ROOT, output_dir)
            payload = json.loads((output_dir / "index.json").read_text(encoding="utf-8"))

            self.assertEqual(payload["formatVersion"], "0.2")
            self.assertEqual(payload["homeId"], "hexrelatum")
            self.assertGreaterEqual(len(payload["concepts"]), 11)
            self.assertEqual(
                [(axis["positive"], axis["negative"]) for axis in payload["axes"]],
                [("Порядок", "Хаос"), ("Действительность", "Вымысел"), ("Конкретное", "Абстрактное")],
            )
            self.assertTrue(all(len(item["coordinates"]) == 6 for item in payload["concepts"]))

            connection = sqlite3.connect(output_dir / "index.sqlite3")
            try:
                count = connection.execute("SELECT COUNT(*) FROM concepts").fetchone()[0]
                self.assertEqual(count, len(payload["concepts"]))
            finally:
                connection.close()

    def test_public_lore_corpus_builds_with_fantasy_axes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            source_root = REPOSITORY_ROOT / "lor"
            build_index.build(REPOSITORY_ROOT, output_dir, source_root)
            payload = json.loads((output_dir / "index.json").read_text(encoding="utf-8"))

            self.assertEqual(payload["homeId"], "geno-dice-open-lore")
            self.assertGreaterEqual(len(payload["concepts"]), 5)
            self.assertEqual(
                [(axis["positive"], axis["negative"]) for axis in payload["axes"]],
                [("Тело", "Дух"), ("Техника", "Реакция"), ("Натиск", "Самообладание")],
            )
            self.assertTrue(all(item["coordinates"] == [1.0] * 6 for item in payload["concepts"]))

    def test_links_are_navigable_both_ways_without_losing_direction(self) -> None:
        payload, directed_links, _ = build_index.build_payload(REPOSITORY_ROOT)
        concepts = {item["id"]: item for item in payload["concepts"]}

        self.assertIn("graph", concepts["cat"]["linkedIds"])
        self.assertIn("cat", concepts["graph"]["linkedIds"])
        self.assertIn(("cat", "graph", "графом", "../mathematics/graph.md"), directed_links)

    def test_equal_pairs_project_to_the_same_local_center(self) -> None:
        def axis(positive: float, negative: float) -> float:
            return (positive - negative) / (positive + negative)

        for value in (1, 2, 6, 100):
            self.assertEqual(axis(value, value), 0)

    def test_rejects_coordinate_below_one(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            wiki_root = Path(temporary)
            article = wiki_root / "invalid.md"
            article.write_text(
                "---\nid: invalid\ntitle: Invalid\ncoordinates: [0, 1, 1, 1, 1, 1]\n---\n",
                encoding="utf-8",
            )
            with self.assertRaises(build_index.IndexBuildError):
                build_index.parse_article(article, wiki_root)

    def test_rejects_incomplete_axis_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "wiki.config.json").write_text(
                '{"axisSemanticsVersion":"preview-v0","axes":[]}', encoding="utf-8"
            )
            with self.assertRaises(build_index.IndexBuildError):
                build_index.load_axes(root)


if __name__ == "__main__":
    unittest.main()
