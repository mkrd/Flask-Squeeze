from __future__ import annotations

import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from typing_extensions import override

from flask_squeeze.cache import CacheEntry, CacheKey, CacheMetadata, StaticFileCache
from flask_squeeze.compress import CompressionStats
from flask_squeeze.minify import MinificationStats
from flask_squeeze.plan import Compression, Encoding, Minification, SqueezePlan
from flask_squeeze.squeeze import SqueezeResult
from tests.sample_app import make_sample_app

GZIP_ONLY_PLAN = SqueezePlan(Compression(Encoding.gzip, 9), None)
GZIP_AND_MINIFY_CSS_PLAN = SqueezePlan(Compression(Encoding.gzip, 9), Minification.css)


def make_cache_entry(request_path: str, plan: SqueezePlan, squeezed_body: bytes) -> CacheEntry:
	minification_stats = None
	if plan.minification is not None:
		minification_stats = MinificationStats(duration_seconds=0.5, size_ratio=2.0)
	compression_stats = None
	if plan.compression is not None:
		compression_stats = CompressionStats(level=9, duration_seconds=0.25, size_ratio=3.0)
	return CacheEntry(
		CacheKey.for_request_path(request_path, plan),
		"original",
		SqueezeResult(squeezed_body, minification_stats, compression_stats),
	)


class PersistentCacheTest(unittest.TestCase):
	@override
	def setUp(self) -> None:
		temp_dir = tempfile.TemporaryDirectory()
		self.addCleanup(temp_dir.cleanup)
		self.tmp_path = Path(temp_dir.name)
		self.cache_dir = self.tmp_path / "cache"

	def fetch_sample_css_cache_status(self, config: dict[str, object] | None = None, encoding: str = "gzip") -> str:
		app = make_sample_app(self.tmp_path, {"SQUEEZE_CACHE_DIR": self.cache_dir, **(config or {})})
		response = app.test_client().get("/static/sample.css", headers={"Accept-Encoding": encoding})
		return response.headers["X-Flask-Squeeze-Cache"]

	def cache_file_count(self) -> int:
		return len(list(self.cache_dir.glob("*.cache")))

	def check_corrupt_entry_is_deleted_and_rewritten(self, expected_body: bytes) -> None:
		app = make_sample_app(self.tmp_path, {"SQUEEZE_CACHE_DIR": self.cache_dir})
		self.assertEqual(list(self.cache_dir.iterdir()), [])
		response = app.test_client().get("/static/sample.css", headers={"Accept-Encoding": "gzip"})
		self.assertEqual(response.headers["X-Flask-Squeeze-Cache"], "MISS")
		self.assertEqual(response.data, expected_body)
		self.assertEqual(self.cache_file_count(), 1)
		self.assertEqual(next(self.cache_dir.glob("*.cache")).read_bytes(), expected_body)
		self.assertEqual(len(list(self.cache_dir.glob("*.meta"))), 1)
		self.assertEqual(self.fetch_sample_css_cache_status(), "HIT")

	def test_entry_is_written_once_and_hit_after_restart(self) -> None:
		self.assertEqual(self.fetch_sample_css_cache_status(), "MISS")
		self.assertEqual(self.fetch_sample_css_cache_status(), "HIT")
		self.assertEqual(self.cache_file_count(), 1)
		self.assertEqual(len(list(self.cache_dir.glob("*.meta"))), 1)

	def test_config_change_replaces_the_variant(self) -> None:
		self.assertEqual(self.fetch_sample_css_cache_status({"SQUEEZE_MINIFY_CSS": True}), "MISS")
		self.assertEqual(self.fetch_sample_css_cache_status({"SQUEEZE_MINIFY_CSS": False}), "MISS")
		self.assertEqual(self.cache_file_count(), 1)
		self.assertEqual(len(list(self.cache_dir.glob("*.meta"))), 1)

		# A different encoding is a separate variant group and coexists
		self.assertEqual(self.fetch_sample_css_cache_status({"SQUEEZE_MINIFY_CSS": False}, encoding="br"), "MISS")
		self.assertEqual(self.cache_file_count(), len(["gzip", "br"]))

	def test_duplicate_variants_on_disk_keep_one(self) -> None:
		other_dir = self.tmp_path / "other"
		StaticFileCache(self.cache_dir).set(make_cache_entry("/static/sample.css", GZIP_ONLY_PLAN, b"plain"))
		StaticFileCache(other_dir).set(make_cache_entry("/static/sample.css", GZIP_AND_MINIFY_CSS_PLAN, b"minified"))
		for file in other_dir.iterdir():
			shutil.copy(file, self.cache_dir / file.name)
		self.assertEqual(self.cache_file_count(), len(["plain", "minified"]))

		StaticFileCache(self.cache_dir)
		self.assertEqual(self.cache_file_count(), 1)
		self.assertEqual(len(list(self.cache_dir.glob("*.meta"))), 1)

	def test_unknown_cache_files_are_discarded(self) -> None:
		self.cache_dir.mkdir(parents=True)
		(self.cache_dir / "old-format.meta").write_text("a\nb\n")
		(self.cache_dir / "old-format.cache").write_bytes(b"x")
		StaticFileCache(self.cache_dir)
		self.assertEqual(list(self.cache_dir.iterdir()), [])

	def test_entries_written_by_an_older_version_are_discarded(self) -> None:
		entry = make_cache_entry("/static/sample.css", GZIP_ONLY_PLAN, b"body")
		StaticFileCache(self.cache_dir).set(entry)
		(self.cache_dir / f"{entry.key.filename_stem}.meta").write_text("original\nsqueezed\n")
		self.assertIsNone(StaticFileCache(self.cache_dir).get(entry.key))
		self.assertEqual(list(self.cache_dir.iterdir()), [])

	def test_corrupt_metadata_is_deleted_and_rewritten(self) -> None:
		self.fetch_sample_css_cache_status()
		cache_file = next(self.cache_dir.glob("*.cache"))
		expected_body = cache_file.read_bytes()
		meta_file = cache_file.with_suffix(".meta")
		metadata_json = meta_file.read_text(encoding="utf-8")
		corrupt_contents = (
			b"\xff",
			b"{",
			metadata_json.replace('"level": 9', '"level": true').encode("utf-8"),
			metadata_json.replace('"level": 9', '"level": -1').encode("utf-8"),
			metadata_json.replace('"level": 9', '"level": 1').encode("utf-8"),
		)
		for content in corrupt_contents:
			with self.subTest(content=content):
				meta_file.write_bytes(content)
				self.check_corrupt_entry_is_deleted_and_rewritten(expected_body)

	def test_corrupt_filename_is_deleted_and_rewritten(self) -> None:
		for level in ("²", "\N{FULLWIDTH DIGIT NINE}", "09", "10", "-1", ""):
			with self.subTest(level=level):
				self.fetch_sample_css_cache_status()
				cache_file = next(self.cache_dir.glob("*.cache"))
				expected_body = cache_file.read_bytes()
				filename_stem = f"{cache_file.stem.rsplit('.', 1)[0]}.{level}"
				cache_file.rename(self.cache_dir / f"{filename_stem}.cache")
				cache_file.with_suffix(".meta").rename(self.cache_dir / f"{filename_stem}.meta")
				self.check_corrupt_entry_is_deleted_and_rewritten(expected_body)

	def test_stats_that_do_not_match_the_key_are_discarded(self) -> None:
		minification_stats = MinificationStats(duration_seconds=0.5, size_ratio=2.0)
		compression_stats = CompressionStats(level=9, duration_seconds=0.25, size_ratio=3.0)
		cases = [
			(GZIP_ONLY_PLAN, SqueezeResult(b"body", minification_stats, compression_stats)),
			(GZIP_AND_MINIFY_CSS_PLAN, SqueezeResult(b"body", minification_stats, None)),
			(SqueezePlan(Compression(Encoding.gzip, 1), None), SqueezeResult(b"body", None, compression_stats)),
		]
		for index, (plan, result) in enumerate(cases):
			with self.subTest(plan=plan):
				cache_dir = self.cache_dir / str(index)
				entry = CacheEntry(CacheKey.for_request_path("/static/sample.css", plan), "original", result)
				StaticFileCache(cache_dir).set(entry)
				self.assertIsNone(StaticFileCache(cache_dir).get(entry.key))
				self.assertEqual(list(cache_dir.iterdir()), [])

	def test_entry_deleted_by_another_process_is_skipped(self) -> None:
		entry = make_cache_entry("/static/sample.css", GZIP_ONLY_PLAN, b"body")
		StaticFileCache(self.cache_dir).set(entry)
		(self.cache_dir / f"{entry.key.filename_stem}.cache").unlink()
		self.assertIsNone(StaticFileCache(self.cache_dir).get(entry.key))

	def test_entry_round_trips_through_disk(self) -> None:
		entry = make_cache_entry("/static/sample.css", GZIP_AND_MINIFY_CSS_PLAN, b"body")
		StaticFileCache(self.cache_dir).set(entry)
		self.assertEqual(StaticFileCache(self.cache_dir).get(entry.key), entry)


class CacheKeyTest(unittest.TestCase):
	def test_filename_stem_round_trip(self) -> None:
		plans = [
			SqueezePlan(Compression(Encoding.br, 11), Minification.js),
			SqueezePlan(None, Minification.js),
			SqueezePlan(Compression(Encoding.gzip, 9), None),
			*(
				SqueezePlan(Compression(encoding, level), None)
				for encoding in Encoding
				for level in (0, encoding.max_level)
			),
		]
		for plan in plans:
			key = CacheKey.for_request_path("/static/a.js", plan)
			with self.subTest(key=key):
				self.assertEqual(CacheKey.from_filename_stem(key.filename_stem), key)

	def test_parse_rejects_foreign_names(self) -> None:
		for stem in (
			"abc.gzip.js",
			"abc.zstd.js.9",
			"abc.gzip.js.none",
			"abc.none.js.9",
			"abc.gzip.js.high",
			"abc.none.none.none",
			"abc.gzip.js.²",
			"abc.gzip.js.\N{FULLWIDTH DIGIT NINE}",
			"abc.gzip.js.09",
			"abc.gzip.js.10",
			"abc.deflate.js.10",
			"abc.br.js.12",
			"abc.gzip.js.-1",
			"abc.gzip.js.",
			f"abc.br.js.{'9' * 5000}",
		):
			with self.subTest(stem=stem):
				self.assertIsNone(CacheKey.from_filename_stem(stem))


class CacheMetadataTest(unittest.TestCase):
	def test_round_trip(self) -> None:
		metadata = CacheMetadata(
			original_body_hash="a",
			squeezed_body_hash="b",
			minification_stats=MinificationStats(duration_seconds=0.5, size_ratio=2.0),
			compression_stats=None,
		)
		self.assertEqual(CacheMetadata.from_json(metadata.to_json()), metadata)

	def test_invalid_compression_levels_are_rejected(self) -> None:
		for level in (True, False, -1):
			with self.subTest(level=level):
				metadata = CacheMetadata("a", "b", None, CompressionStats(level, 0.25, 3.0))
				self.assertIsNone(CacheMetadata.from_json(metadata.to_json()))

	def test_invalid_statistics_are_rejected(self) -> None:
		minification = MinificationStats(0.5, 2.0)
		compression = CompressionStats(9, 0.25, 3.0)
		metadata = CacheMetadata("a", "b", minification, compression)
		for value in (float("nan"), float("inf"), float("-inf"), -1.0):
			cases = (
				replace(metadata, minification_stats=replace(minification, duration_seconds=value)),
				replace(metadata, minification_stats=replace(minification, size_ratio=value)),
				replace(metadata, compression_stats=replace(compression, duration_seconds=value)),
				replace(metadata, compression_stats=replace(compression, size_ratio=value)),
			)
			for case in cases:
				with self.subTest(metadata=case):
					self.assertIsNone(CacheMetadata.from_json(case.to_json()))

	def test_zero_statistics_round_trip(self) -> None:
		metadata = CacheMetadata("a", "b", MinificationStats(0.0, 0.0), CompressionStats(0, 0.0, 0.0))
		self.assertEqual(CacheMetadata.from_json(metadata.to_json()), metadata)

	def test_parse_rejects_foreign_content(self) -> None:
		for text in (
			"original\nsqueezed\n",
			"[]",
			'{"original_body_hash": "a"}',
			'{"original_body_hash": "a", "squeezed_body_hash": 1}',
			'{"original_body_hash": "a", "squeezed_body_hash": "b", "compression_stats": {"level": 9}}',
			f'{{"level": {"9" * 5000}}}',
			"[" * 10000 + "]" * 10000,
		):
			with self.subTest(text=text):
				self.assertIsNone(CacheMetadata.from_json(text))
