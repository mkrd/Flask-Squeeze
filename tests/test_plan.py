from __future__ import annotations

import unittest
from dataclasses import dataclass

from flask import Config

from flask_squeeze.config import SqueezeConfig
from flask_squeeze.extension import plan_squeeze, resource_type_for_endpoint
from flask_squeeze.plan import Compression, Encoding, Minification, ResourceType, SqueezePlan

DEFAULT_CONFIG = SqueezeConfig.from_flask_config(Config("."))


@dataclass(frozen=True)
class PlanCase:
	name: str
	accept_encoding: str | None
	mimetype: str | None
	resource_type: ResourceType
	expected: SqueezePlan | None
	config: SqueezeConfig = DEFAULT_CONFIG


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
]


class PlanSqueezeTest(unittest.TestCase):
	def test_plan_squeeze(self) -> None:
		for case in PLAN_CASES:
			with self.subTest(case.name):
				plan = plan_squeeze(case.config, case.accept_encoding, case.mimetype, case.resource_type)
				self.assertEqual(plan, case.expected)

	def test_resource_type_of(self) -> None:
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

	def test_plan_needs_compression_or_minification(self) -> None:
		with self.assertRaises(ValueError):
			SqueezePlan(None, None)
