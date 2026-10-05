from __future__ import annotations

import itertools
import unittest
from dataclasses import replace
from pathlib import Path

from flask import Config

from flask_squeeze.config import SqueezeConfig
from flask_squeeze.plan import Encoding, Minification, ResourceType

ALL_MINIFICATIONS_DISABLED = {minification.enable_config_key: False for minification in Minification}


def parse(values: dict[str, object]) -> SqueezeConfig:
	return SqueezeConfig.from_flask_config(Config(".", values))


class SqueezeConfigTest(unittest.TestCase):
	def test_defaults(self) -> None:
		config = parse({})
		self.assertTrue(config.compression_enabled)
		self.assertEqual(config.min_response_size, 500)
		self.assertEqual(config.enabled_minifications, frozenset(Minification))
		self.assertIsNone(config.cache_dir)
		self.assertFalse(config.info_headers_enabled)
		expected_levels = {
			(Encoding.br, ResourceType.static): 11,
			(Encoding.gzip, ResourceType.static): 9,
			(Encoding.deflate, ResourceType.static): 9,
			(Encoding.br, ResourceType.dynamic): 1,
			(Encoding.gzip, ResourceType.dynamic): 1,
			(Encoding.deflate, ResourceType.dynamic): 1,
		}
		self.assertEqual(config.compression_levels, expected_levels)

	def test_level_bounds_are_inclusive(self) -> None:
		for encoding, resource_type in itertools.product(Encoding, ResourceType):
			for level in (0, encoding.max_level):
				with self.subTest(encoding=encoding, resource_type=resource_type, level=level):
					config = parse({encoding.level_config_key(resource_type): level})
					self.assertEqual(config.compression_level(encoding, resource_type), level)

	def test_compression_levels_do_not_retain_mutable_aliases(self) -> None:
		original = parse({})
		levels = dict(original.compression_levels)
		config = replace(original, compression_levels=levels)
		levels[Encoding.gzip, ResourceType.static] = 1
		self.assertEqual(config.compression_level(Encoding.gzip, ResourceType.static), 9)

	def test_direct_construction_rejects_invalid_compression_levels(self) -> None:
		config = parse({})
		levels = dict(config.compression_levels)
		levels[Encoding.gzip, ResourceType.static] = 10
		with self.assertRaises(ValueError):
			replace(config, compression_levels=levels)

	def test_invalid_values_name_the_key(self) -> None:
		cases: list[tuple[str, object, type[Exception]]] = [
			("SQUEEZE_LEVEL_BROTLI_STATIC", 12, ValueError),
			("SQUEEZE_LEVEL_GZIP_STATIC", 10, ValueError),
			("SQUEEZE_LEVEL_DEFLATE_DYNAMIC", 10, ValueError),
			("SQUEEZE_LEVEL_GZIP_DYNAMIC", -1, ValueError),
			("SQUEEZE_LEVEL_GZIP_STATIC", "9", TypeError),
			("SQUEEZE_LEVEL_GZIP_STATIC", 9.0, TypeError),
			("SQUEEZE_LEVEL_BROTLI_DYNAMIC", True, TypeError),
			("SQUEEZE_MIN_SIZE", -1, ValueError),
			("SQUEEZE_MIN_SIZE", False, TypeError),
			("SQUEEZE_COMPRESS", "yes", TypeError),
			("SQUEEZE_COMPRESS", None, TypeError),
			("SQUEEZE_INFO_HEADERS", 1, TypeError),
			("SQUEEZE_MINIFY_HTML", 0, TypeError),
			("SQUEEZE_CACHE_DIR", 1, TypeError),
			("SQUEEZE_CACHE_DIR", b"cache", TypeError),
		]
		for key, value, error in cases:
			with self.subTest(key=key, value=value), self.assertRaisesRegex(error, key):
				parse({key: value})

	def test_unknown_keys_are_all_listed(self) -> None:
		with self.assertRaisesRegex(ValueError, "SQUEEZE_LEVEL_BR_STATIC, SQUEEZE_MINIFY_JSS"):
			parse({"SQUEEZE_MINIFY_JSS": False, "SQUEEZE_LEVEL_BR_STATIC": 5})

	def test_keys_without_the_prefix_are_ignored(self) -> None:
		self.assertEqual(parse({"SECRET_KEY": "x", "SQUEEZEMINIFY": 1}), parse({}))

	def test_cache_dir_accepts_str_and_path(self) -> None:
		for value in ("cache/squeeze", Path("cache/squeeze")):
			with self.subTest(value=value):
				self.assertEqual(parse({"SQUEEZE_CACHE_DIR": value}).cache_dir, Path("cache/squeeze"))

	def test_squeezing_enabled(self) -> None:
		cases: list[tuple[dict[str, object], bool]] = [
			({}, True),
			({"SQUEEZE_COMPRESS": False}, True),
			({**ALL_MINIFICATIONS_DISABLED}, True),
			({**ALL_MINIFICATIONS_DISABLED, "SQUEEZE_COMPRESS": False, "SQUEEZE_MINIFY_JS": True}, True),
			({**ALL_MINIFICATIONS_DISABLED, "SQUEEZE_COMPRESS": False}, False),
		]
		for values, expected in cases:
			with self.subTest(values=values):
				self.assertIs(parse(values).squeezing_enabled, expected)
