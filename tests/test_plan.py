from __future__ import annotations

import unittest
from dataclasses import dataclass

from flask import Config

from flask_squeeze.config import SqueezeConfig
from flask_squeeze.extension import plan_squeeze, resource_type_for_endpoint
from flask_squeeze.negotiate import negotiate_encoding
from flask_squeeze.plan import Compression, Encoding, Minification, ResourceType, SqueezePlan
from flask_squeeze.squeeze import apply_squeeze_plan
from tests.sample_app import CSS, MINIFIED_CSS, decompress

DEFAULT_CONFIG = SqueezeConfig.from_flask_config(Config("."))


@dataclass(frozen=True)
class PlanCase:
	name: str
	accept_encoding: str | None
	mimetype: str | None
	resource_type: ResourceType
	expected: SqueezePlan | None
	config: SqueezeConfig = DEFAULT_CONFIG
	charset: str | None = None


PLAN_CASES = [
	PlanCase(
		"static gets the static level",
		"br",
		"text/css",
		ResourceType.static,
		SqueezePlan(Compression(Encoding.br, 11), Minification.css),
	),
	PlanCase(
		"dynamic gets the dynamic level",
		"gzip",
		"text/javascript",
		ResourceType.dynamic,
		SqueezePlan(Compression(Encoding.gzip, 1), Minification.js),
	),
	PlanCase(
		"no accepted encoding still minifies",
		None,
		"text/html",
		ResourceType.dynamic,
		SqueezePlan(None, Minification.html),
	),
	PlanCase("nothing applies", None, "application/json", ResourceType.dynamic, None),
	PlanCase(
		"missing mimetype only compresses",
		"gzip",
		None,
		ResourceType.dynamic,
		SqueezePlan(Compression(Encoding.gzip, 1), None),
	),
	PlanCase(
		"similar mimetype is not minified",
		"gzip",
		"text/x-scss",
		ResourceType.static,
		SqueezePlan(Compression(Encoding.gzip, 9), None),
	),
	PlanCase(
		"compression disabled",
		"gzip",
		"text/css",
		ResourceType.static,
		SqueezePlan(None, Minification.css),
		SqueezeConfig.from_flask_config(Config(".", {"SQUEEZE_COMPRESS": False})),
	),
	PlanCase(
		"minification disabled",
		"gzip",
		"text/css",
		ResourceType.static,
		SqueezePlan(Compression(Encoding.gzip, 9), None),
		SqueezeConfig.from_flask_config(Config(".", {"SQUEEZE_MINIFY_CSS": False})),
	),
	PlanCase(
		"declared utf-8 is minified",
		"gzip",
		"text/css",
		ResourceType.dynamic,
		SqueezePlan(Compression(Encoding.gzip, 1), Minification.css),
		charset="UTF-8",
	),
	PlanCase(
		"other charsets are only compressed",
		"gzip",
		"text/css",
		ResourceType.dynamic,
		SqueezePlan(Compression(Encoding.gzip, 1), None),
		charset="iso-8859-1",
	),
	PlanCase("other charsets without compression", None, "text/html", ResourceType.dynamic, None, charset="ascii"),
]


class PlanSqueezeTest(unittest.TestCase):
	def test_plan_squeeze(self) -> None:
		for case in PLAN_CASES:
			with self.subTest(case.name):
				negotiated = negotiate_encoding(case.accept_encoding)
				encoding = negotiated if isinstance(negotiated, Encoding) else None
				plan = plan_squeeze(case.config, encoding, case.mimetype, case.charset, case.resource_type)
				self.assertEqual(plan, case.expected)

	def test_resource_type_for_endpoint(self) -> None:
		cases = [
			("static", ResourceType.static),
			("assets.static", ResourceType.static),
			("index", ResourceType.dynamic),
			("mystatic", ResourceType.dynamic),
			(None, ResourceType.dynamic),
		]
		for endpoint, expected in cases:
			with self.subTest(endpoint=endpoint):
				self.assertEqual(resource_type_for_endpoint(endpoint), expected)


class SqueezePlanTest(unittest.TestCase):
	def test_plan_needs_compression_or_minification(self) -> None:
		with self.assertRaisesRegex(ValueError, "needs a compression, a minification, or both"):
			SqueezePlan(None, None)

	def test_minification_for_mimetype(self) -> None:
		cases = [
			("text/html", Minification.html),
			("text/css", Minification.css),
			("text/javascript", Minification.js),
			("application/javascript", Minification.js),
			("application/x-javascript", Minification.js),
			("application/json", None),
			("application/xhtml+xml", None),
			("image/svg+xml", None),
			(None, None),
		]
		for mimetype, expected in cases:
			with self.subTest(mimetype=mimetype):
				self.assertIs(Minification.for_mimetype(mimetype), expected)

	def test_minification_for_mimetype_ignores_case(self) -> None:
		self.assertIs(Minification.for_mimetype("Text/HTML"), Minification.html)
		self.assertIs(Minification.for_mimetype("APPLICATION/JAVASCRIPT"), Minification.js)


class ApplySqueezePlanTest(unittest.TestCase):
	def test_minifies_before_compressing(self) -> None:
		result = apply_squeeze_plan(CSS, SqueezePlan(Compression(Encoding.gzip, 9), Minification.css))
		self.assertEqual(decompress(result.squeezed_body, Encoding.gzip), MINIFIED_CSS)
		self.assertIsNotNone(result.minification_stats)
		self.assertIsNotNone(result.compression_stats)

	def test_skipped_steps_have_no_stats(self) -> None:
		minified = apply_squeeze_plan(CSS, SqueezePlan(None, Minification.css))
		self.assertEqual(minified.squeezed_body, MINIFIED_CSS)
		self.assertIsNone(minified.compression_stats)

		compressed = apply_squeeze_plan(CSS, SqueezePlan(Compression(Encoding.br, 5), None))
		self.assertEqual(decompress(compressed.squeezed_body, Encoding.br), CSS)
		self.assertIsNone(compressed.minification_stats)


class CompressionPlanTest(unittest.TestCase):
	def test_invalid_levels_fail_at_construction(self) -> None:
		for encoding in Encoding:
			for level in (-1, encoding.max_level + 1):
				with self.subTest(encoding=encoding, level=level), self.assertRaises(ValueError):
					Compression(encoding, level)
			for level in (True, False):
				with self.subTest(encoding=encoding, level=level), self.assertRaises(TypeError):
					Compression(encoding, level)
