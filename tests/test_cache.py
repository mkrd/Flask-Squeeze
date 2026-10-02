from __future__ import annotations

import hashlib
import os
import shutil
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier
from typing import TYPE_CHECKING
from unittest.mock import patch

from flask_squeeze.cache import (
	CACHE_FORMAT_MAGIC,
	CACHE_HEADER_BYTES,
	METADATA_LENGTH_BYTES,
	CacheEntry,
	CacheKey,
	CacheMetadata,
	StaticFileCache,
)
from flask_squeeze.compress import CompressionStats
from flask_squeeze.minify import MinificationStats
from flask_squeeze.plan import Compression, Encoding, Minification, SqueezePlan
from flask_squeeze.squeeze import SqueezeResult
from tests.sample_app import SampleAppTestCase

if TYPE_CHECKING:
	from collections.abc import Callable, Mapping

GZIP_ONLY_PLAN = SqueezePlan(Compression(Encoding.gzip, 9), None)
GZIP_AND_MINIFY_CSS_PLAN = SqueezePlan(Compression(Encoding.gzip, 9), Minification.css)


def make_cache_entry(request_path: str, plan: SqueezePlan, squeezed_body: bytes) -> CacheEntry:
	minification_stats = None
	if plan.minification is not None:
		minification_stats = MinificationStats(duration_seconds=0.5, size_ratio=2.0)
	compression_stats = None
	if plan.compression is not None:
		compression_stats = CompressionStats(level=plan.compression.level, duration_seconds=0.25, size_ratio=3.0)
	return CacheEntry(
		CacheKey.for_request_path(request_path, plan),
		"original",
		SqueezeResult(squeezed_body, minification_stats, compression_stats),
	)


def replace_first_metadata_byte(content: bytes, replacement: bytes) -> bytes:
	return content[:CACHE_HEADER_BYTES] + replacement + content[CACHE_HEADER_BYTES + 1 :]


class PersistentCacheTest(SampleAppTestCase):
	def fetch_sample_css_cache_status(self, config: dict[str, object] | None = None, encoding: str = "gzip") -> str:
		app = self.make_app({"SQUEEZE_CACHE_DIR": self.cache_dir, **(config or {})})
		response = app.test_client().get("/static/sample.css", headers={"Accept-Encoding": encoding})
		return response.headers["X-Flask-Squeeze-Cache"]

	def cache_file_count(self) -> int:
		return len(list(self.cache_dir.glob("*.cache")))

	def read_cache_entry(self) -> CacheEntry:
		cache_file = next(self.cache_dir.glob("*.cache"))
		entry = CacheEntry.from_bytes(cache_file.stem, cache_file.read_bytes())
		if entry is None:
			self.fail("Expected a valid persisted cache entry")
		return entry

	def write_fresh_cache_file(self) -> tuple[Path, bytes]:
		"""Start from an empty cache dir holding one valid entry. Returns its file and squeezed body."""
		shutil.rmtree(self.cache_dir, ignore_errors=True)
		self.assertEqual(self.fetch_sample_css_cache_status(), "MISS")
		return next(self.cache_dir.glob("*.cache")), self.read_cache_entry().squeeze_result.squeezed_body

	def check_corrupt_entry_is_deleted_and_rewritten(self, expected_body: bytes) -> None:
		app = self.make_app({"SQUEEZE_CACHE_DIR": self.cache_dir})
		self.assertEqual(list(self.cache_dir.iterdir()), [])
		response = app.test_client().get("/static/sample.css", headers={"Accept-Encoding": "gzip"})
		self.assertEqual(response.headers["X-Flask-Squeeze-Cache"], "MISS")
		self.assertEqual(response.data, expected_body)
		self.assertEqual(self.cache_file_count(), 1)
		self.assertEqual(self.read_cache_entry().squeeze_result.squeezed_body, expected_body)
		self.assertEqual(list(self.cache_dir.glob("*.meta")), [])
		self.assertEqual(self.fetch_sample_css_cache_status(), "HIT")

	def test_entry_is_written_once_and_hit_after_restart(self) -> None:
		self.assertEqual(self.fetch_sample_css_cache_status(), "MISS")
		self.assertEqual(self.fetch_sample_css_cache_status(), "HIT")
		self.assertEqual(self.cache_file_count(), 1)
		self.assertEqual(list(self.cache_dir.glob("*.meta")), [])

	def test_config_change_replaces_the_variant(self) -> None:
		self.assertEqual(self.fetch_sample_css_cache_status({"SQUEEZE_MINIFY_CSS": True}), "MISS")
		self.assertEqual(self.fetch_sample_css_cache_status({"SQUEEZE_MINIFY_CSS": False}), "MISS")
		self.assertEqual(self.cache_file_count(), 1)
		self.assertEqual(list(self.cache_dir.glob("*.meta")), [])

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
		self.assertEqual(list(self.cache_dir.glob("*.meta")), [])

	def test_unknown_cache_files_are_discarded(self) -> None:
		self.cache_dir.mkdir(parents=True)
		(self.cache_dir / "old-format.meta").write_text("a\nb\n")
		(self.cache_dir / "old-format.cache").write_bytes(b"x")
		StaticFileCache(self.cache_dir)
		self.assertEqual(list(self.cache_dir.iterdir()), [])

	def test_entries_written_by_an_older_version_are_deleted_and_rewritten(self) -> None:
		self.fetch_sample_css_cache_status()
		entry = self.read_cache_entry()
		body = entry.squeeze_result.squeezed_body
		metadata = CacheMetadata(
			entry.original_body_hash,
			hashlib.sha256(body).hexdigest(),
			entry.squeeze_result.minification_stats,
			entry.squeeze_result.compression_stats,
		)
		cache_file = self.cache_dir / f"{entry.key.filename_stem}.cache"
		cache_file.write_bytes(body)
		cache_file.with_suffix(".meta").write_text(metadata.to_json(), encoding="utf-8")
		self.check_corrupt_entry_is_deleted_and_rewritten(body)

	def test_orphaned_legacy_metadata_is_deleted(self) -> None:
		self.cache_dir.mkdir()
		(self.cache_dir / "orphan.meta").write_bytes(b"\xff")
		StaticFileCache(self.cache_dir)
		self.assertEqual(list(self.cache_dir.iterdir()), [])

	def test_legacy_metadata_does_not_delete_a_valid_single_file_entry(self) -> None:
		entry = make_cache_entry("/static/sample.css", GZIP_ONLY_PLAN, b"body")
		StaticFileCache(self.cache_dir).set(entry)
		(self.cache_dir / f"{entry.key.filename_stem}.meta").write_bytes(b"\xff")
		self.assertEqual(StaticFileCache(self.cache_dir).get(entry.key), entry)
		self.assertEqual(list(self.cache_dir.glob("*.meta")), [])

	def check_corruptions_are_deleted_and_rewritten(self, corruptions: Mapping[str, Callable[[bytes], bytes]]) -> None:
		for name, corrupt in corruptions.items():
			with self.subTest(name):
				cache_file, expected_body = self.write_fresh_cache_file()
				cache_file.write_bytes(corrupt(cache_file.read_bytes()))
				self.check_corrupt_entry_is_deleted_and_rewritten(expected_body)

	def test_corrupt_metadata_is_deleted_and_rewritten(self) -> None:
		self.check_corruptions_are_deleted_and_rewritten(
			{
				"invalid utf-8": lambda content: replace_first_metadata_byte(content, b"\xff"),
				"invalid json": lambda content: replace_first_metadata_byte(content, b"["),
				"bool level": lambda content: content.replace(b'"level": 9', b'"level": true'),
				"negative level": lambda content: content.replace(b'"level": 9', b'"level": -1'),
				"level differs from filename": lambda content: content.replace(b'"level": 9', b'"level": 1'),
			}
		)

	def test_incomplete_entries_are_deleted_and_rewritten(self) -> None:
		self.check_corruptions_are_deleted_and_rewritten(
			{
				"empty": lambda _content: b"",
				"magic only": lambda content: content[: len(CACHE_FORMAT_MAGIC)],
				"header and one byte": lambda content: content[: CACHE_HEADER_BYTES + 1],
				"last byte missing": lambda content: content[:-1],
			}
		)

	def test_corrupt_filename_is_deleted_and_rewritten(self) -> None:
		for level in ("²", "\N{FULLWIDTH DIGIT NINE}", "09", "10", "-1", ""):
			with self.subTest(level=level):
				cache_file, expected_body = self.write_fresh_cache_file()
				filename_stem = f"{cache_file.stem.rsplit('.', 1)[0]}.{level}"
				cache_file.rename(self.cache_dir / f"{filename_stem}.cache")
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
				cache_dir.mkdir(parents=True)
				key = CacheKey.for_request_path("/static/sample.css", plan)
				metadata = CacheMetadata(
					"original",
					hashlib.sha256(result.squeezed_body).hexdigest(),
					result.minification_stats,
					result.compression_stats,
				)
				metadata_bytes = metadata.to_json().encode("utf-8")
				content = (
					CACHE_FORMAT_MAGIC
					+ len(metadata_bytes).to_bytes(METADATA_LENGTH_BYTES, "big")
					+ metadata_bytes
					+ result.squeezed_body
				)
				(cache_dir / f"{key.filename_stem}.cache").write_bytes(content)
				self.assertIsNone(StaticFileCache(cache_dir).get(key))
				self.assertEqual(list(cache_dir.iterdir()), [])

	def test_entry_deleted_between_listing_and_reading_is_skipped(self) -> None:
		entry = make_cache_entry("/static/sample.css", GZIP_ONLY_PLAN, b"body")
		other_entry = make_cache_entry("/static/sample.js", GZIP_ONLY_PLAN, b"other")
		StaticFileCache(self.cache_dir).set(entry)
		StaticFileCache(self.cache_dir).set(other_entry)
		deleted_path = self.cache_dir / f"{entry.key.filename_stem}.cache"
		read_bytes = Path.read_bytes

		def read_after_other_process_deleted(path: Path) -> bytes:
			if path == deleted_path:
				path.unlink()
			return read_bytes(path)

		with patch.object(Path, "read_bytes", autospec=True, side_effect=read_after_other_process_deleted) as reader:
			cache = StaticFileCache(self.cache_dir)
		self.assertIn(deleted_path, [call.args[0] for call in reader.call_args_list])
		self.assertIsNone(cache.get(entry.key))
		self.assertEqual(cache.get(other_entry.key), other_entry)

	def test_entry_round_trips_through_disk(self) -> None:
		entry = make_cache_entry("/static/sample.css", GZIP_AND_MINIFY_CSS_PLAN, b"body")
		StaticFileCache(self.cache_dir).set(entry)
		self.assertEqual(StaticFileCache(self.cache_dir).get(entry.key), entry)

	def test_replacement_publishes_a_complete_entry(self) -> None:
		cache = StaticFileCache(self.cache_dir)
		original = make_cache_entry("/static/sample.css", GZIP_ONLY_PLAN, b"original body")
		updated = make_cache_entry("/static/sample.css", GZIP_ONLY_PLAN, b"updated body")
		cache.set(original)
		replace_file = os.replace

		def publish(source: Path, destination: Path) -> None:
			self.assertEqual(source.parent, destination.parent)
			self.assertEqual(source.read_bytes(), updated.to_bytes())
			self.assertEqual(destination.read_bytes(), original.to_bytes())
			self.assertEqual(StaticFileCache(self.cache_dir).get(original.key), original)
			replace_file(source, destination)

		with patch.object(os, "replace", side_effect=publish) as replacement:
			cache.set(updated)
			replacement.assert_called_once()
		self.assertEqual(cache.get(updated.key), updated)
		self.assertEqual(StaticFileCache(self.cache_dir).get(updated.key), updated)
		self.assertEqual(list(self.cache_dir.glob("*.tmp")), [])

	def test_failed_replacement_preserves_the_previous_entry(self) -> None:
		cache = StaticFileCache(self.cache_dir)
		original = make_cache_entry("/static/sample.css", GZIP_ONLY_PLAN, b"original body")
		original_path = self.cache_dir / f"{original.key.filename_stem}.cache"
		cache.set(original)
		for plan in (GZIP_ONLY_PLAN, GZIP_AND_MINIFY_CSS_PLAN):
			with self.subTest(plan=plan):
				updated = make_cache_entry("/static/sample.css", plan, b"updated body")
				with (
					patch.object(os, "replace", side_effect=OSError("Replacement failed")),
					self.assertRaisesRegex(OSError, "Replacement failed"),
				):
					cache.set(updated)
				self.assertEqual(cache.get(original.key), original)
				self.assertEqual(StaticFileCache(self.cache_dir).get(original.key), original)
				self.assertEqual(list(self.cache_dir.iterdir()), [original_path])

	def test_concurrent_variant_updates_keep_memory_and_disk_consistent(self) -> None:
		cache = StaticFileCache(self.cache_dir)
		entries = tuple(
			make_cache_entry("/static/sample.css", SqueezePlan(Compression(Encoding.gzip, level), None), b"body")
			for level in range(4)
		)
		barrier = Barrier(len(entries))

		def store(entry: CacheEntry) -> None:
			barrier.wait(timeout=10)
			for _ in range(20):
				cache.set(entry)

		with ThreadPoolExecutor(max_workers=len(entries)) as executor:
			futures = [executor.submit(store, entry) for entry in entries]
			for future in futures:
				future.result(timeout=10)

		entry = self.read_cache_entry()
		self.assertEqual(cache.get(entry.key), entry)
		self.assertEqual(self.cache_file_count(), 1)
		self.assertEqual(list(self.cache_dir.glob("*.tmp")), [])

	def test_independent_cache_instances_publish_complete_entries(self) -> None:
		entries = tuple(
			make_cache_entry("/static/sample.css", GZIP_ONLY_PLAN, bytes([index]) * 65536) for index in range(4)
		)
		caches = tuple(StaticFileCache(self.cache_dir) for _ in entries)
		barrier = Barrier(len(entries))

		def store(index: int) -> None:
			barrier.wait(timeout=10)
			for _ in range(20):
				caches[index].set(entries[index])

		with ThreadPoolExecutor(max_workers=len(entries)) as executor:
			futures = [executor.submit(store, index) for index in range(len(entries))]
			for future in futures:
				future.result(timeout=10)

		entry = self.read_cache_entry()
		self.assertIn(entry, entries)
		self.assertEqual(StaticFileCache(self.cache_dir).get(entry.key), entry)
		self.assertEqual(self.cache_file_count(), 1)
		self.assertEqual(list(self.cache_dir.glob("*.tmp")), [])


class InMemoryCacheTest(unittest.TestCase):
	def test_variant_replaces_the_other_variant_of_its_encoding(self) -> None:
		cache = StaticFileCache(None)
		plain = make_cache_entry("/static/sample.css", GZIP_ONLY_PLAN, b"plain")
		brotli_entry = make_cache_entry("/static/sample.css", SqueezePlan(Compression(Encoding.br, 11), None), b"br")
		minified = make_cache_entry("/static/sample.css", GZIP_AND_MINIFY_CSS_PLAN, b"minified")
		for entry in (plain, brotli_entry, minified):
			cache.set(entry)
		self.assertIsNone(cache.get(plain.key))
		self.assertEqual(cache.get(minified.key), minified)
		self.assertEqual(cache.get(brotli_entry.key), brotli_entry)

	def test_other_paths_miss(self) -> None:
		cache = StaticFileCache(None)
		cache.set(make_cache_entry("/static/a.css", GZIP_ONLY_PLAN, b"a"))
		self.assertIsNone(cache.get(CacheKey.for_request_path("/static/b.css", GZIP_ONLY_PLAN)))


class CacheEntryTest(unittest.TestCase):
	def test_stats_that_do_not_match_the_plan_are_rejected_at_construction(self) -> None:
		minification_stats = MinificationStats(duration_seconds=0.5, size_ratio=2.0)
		compression_stats = CompressionStats(level=9, duration_seconds=0.25, size_ratio=3.0)
		cases = (
			(GZIP_ONLY_PLAN, SqueezeResult(b"body", minification_stats, compression_stats)),
			(GZIP_AND_MINIFY_CSS_PLAN, SqueezeResult(b"body", None, compression_stats)),
			(GZIP_AND_MINIFY_CSS_PLAN, SqueezeResult(b"body", minification_stats, None)),
			(SqueezePlan(None, Minification.css), SqueezeResult(b"body", minification_stats, compression_stats)),
			(SqueezePlan(Compression(Encoding.gzip, 1), None), SqueezeResult(b"body", None, compression_stats)),
		)
		for plan, result in cases:
			with self.subTest(plan=plan, result=result), self.assertRaises(ValueError):
				CacheEntry(CacheKey.for_request_path("/static/sample.css", plan), "original", result)

	def test_single_file_round_trip(self) -> None:
		plans = (
			GZIP_ONLY_PLAN,
			GZIP_AND_MINIFY_CSS_PLAN,
			SqueezePlan(None, Minification.css),
			SqueezePlan(Compression(Encoding.br, 11), Minification.js),
			SqueezePlan(Compression(Encoding.deflate, 0), None),
		)
		for plan in plans:
			for body in (b"", b"\x00\xff\nbody"):
				with self.subTest(plan=plan, body=body):
					entry = make_cache_entry("/static/sample.css", plan, body)
					self.assertEqual(CacheEntry.from_bytes(entry.key.filename_stem, entry.to_bytes()), entry)

	def test_incomplete_or_incompatible_files_are_rejected(self) -> None:
		entry = make_cache_entry("/static/sample.css", GZIP_ONLY_PLAN, b"body")
		content = entry.to_bytes()
		corrupt_contents = (
			b"",
			CACHE_FORMAT_MAGIC,
			b"FSQ2" + content[len(CACHE_FORMAT_MAGIC) :],
			CACHE_FORMAT_MAGIC + b"\x00\x00\x00\x00",
			CACHE_FORMAT_MAGIC + b"\xff\xff\xff\xff" + content[CACHE_HEADER_BYTES:],
			content[:-1],
			content + b"extra",
		)
		for corrupt_content in corrupt_contents:
			with self.subTest(content=corrupt_content):
				self.assertIsNone(CacheEntry.from_bytes(entry.key.filename_stem, corrupt_content))


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
