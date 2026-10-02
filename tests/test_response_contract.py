from __future__ import annotations

import itertools
import shutil
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from flask import Flask, Response
from typing_extensions import override

from flask_squeeze import Squeeze
from flask_squeeze.plan import Encoding, ResourceType
from tests.sample_app import CSS, HTML, JS, decoded_body, make_sample_app

if TYPE_CHECKING:
	from collections.abc import Mapping

STATUS_OK = 200
STATUS_PARTIAL_CONTENT = 206
STATUS_NOT_MODIFIED = 304
MINIFIED_CSS = b".box{color:red;margin:0}"
FIXTURES_DIR = Path(__file__).parent / "fixtures"
INFO_HEADER_NAMES = ("X-Flask-Squeeze-Minify", "X-Flask-Squeeze-Compress", "X-Flask-Squeeze-Cache")


@dataclass(frozen=True)
class AssetCase:
	file_extension: str
	source: bytes
	minified: bytes


ASSET_CASES = [
	AssetCase("css", CSS, MINIFIED_CSS),
	AssetCase("js", JS, b"const answer=42"),
	AssetCase("html", HTML, b"<p>Hello"),
]


class ResponseContractTest(unittest.TestCase):
	@override
	def setUp(self) -> None:
		temp_dir = tempfile.TemporaryDirectory()
		self.addCleanup(temp_dir.cleanup)
		self.tmp_path = Path(temp_dir.name)
		self.cache_dir = self.tmp_path / "cache"

	def make_app(self, config: Mapping[str, object] | None = None) -> Flask:
		return make_sample_app(self.tmp_path, config)

	####################################################################################
	#### MARK: Body and headers

	def test_response_body_contract(self) -> None:
		for static in (False, True):
			for asset in ASSET_CASES:
				for minify in (False, True):
					for encoding in ("", "gzip", "deflate", "br"):
						with self.subTest(static=static, asset=asset.file_extension, minify=minify, encoding=encoding):
							self.check_response_body_contract(encoding, asset, minify=minify, static=static)

	def check_response_body_contract(self, encoding: str, asset: AssetCase, *, minify: bool, static: bool) -> None:
		app = self.make_app({"SQUEEZE_MINIFY_CSS": minify, "SQUEEZE_MINIFY_JS": minify, "SQUEEZE_MINIFY_HTML": minify})
		path = f"/static/sample.{asset.file_extension}" if static else f"/dynamic.{asset.file_extension}"
		response = app.test_client().get(path, headers={"Accept-Encoding": encoding})
		self.assertEqual(response.status_code, STATUS_OK)
		self.assertEqual(response.headers["Content-Length"], str(len(response.data)))
		self.assertEqual(response.headers.get("Content-Encoding", ""), encoding)
		self.assertIs("X-Flask-Squeeze-Minify" in response.headers, minify)
		self.assertIs("X-Flask-Squeeze-Compress" in response.headers, bool(encoding))
		self.assertIn("Accept-Encoding", response.headers.get("Vary", ""))

		self.assertEqual(decoded_body(response), asset.minified if minify else asset.source)

	def test_rendered_template_is_minified(self) -> None:
		client = self.make_app().test_client()
		for encoding in ("", "gzip", "br"):
			with self.subTest(encoding=encoding):
				response = client.get("/", headers={"Accept-Encoding": encoding})
				self.assertEqual(response.headers.get("Content-Encoding", ""), encoding)
				body = decoded_body(response)
				self.assertTrue(body.startswith(b"<!DOCTYPE html>"))
				self.assertIn(b".some-test-class{color:red}", body)
				self.assertIn(b"function someTestFunction()", body)
				self.assertNotIn(b"\n\t\t", body)

	def test_accept_encoding_quality(self) -> None:
		cases = [
			("gzip;q=0", ""),
			("br;q=0, gzip;q=1", "gzip"),
			("gzip;q=0.5, br;q=0.8", "br"),
			("gzip;q=0.8, br;q=0.5", "gzip"),
			("*;q=0.5", "br"),
			("gzip;q=0, *;q=0.5", "br"),
			("gzip, br, deflate", "br"),
			("deflate, gzip", "gzip"),
			("deflate", "deflate"),
			("xgzip", ""),
		]
		client = self.make_app({"SQUEEZE_MINIFY_CSS": False}).test_client()
		for accepted, expected in cases:
			with self.subTest(accepted=accepted):
				response = client.get("/static/sample.css", headers={"Accept-Encoding": accepted})
				self.assertEqual(response.headers.get("Content-Encoding", ""), expected)
				self.assertEqual(decoded_body(response), CSS)

	def test_json_is_data_not_javascript(self) -> None:
		response = self.make_app().test_client().get("/json")
		self.assertEqual(response.data, b"[1, 2, 3]")
		self.assertNotIn("X-Flask-Squeeze-Minify", response.headers)

	def test_similar_mimetype_is_not_minified(self) -> None:
		(self.tmp_path / "style.scss").write_bytes(b".a { .b { color: red; } }")
		response = self.make_app().test_client().get("/static/style.scss", headers={"Accept-Encoding": "gzip"})
		self.assertNotIn("X-Flask-Squeeze-Minify", response.headers)
		self.assertEqual(decoded_body(response), b".a { .b { color: red; } }")

	def test_binary_file_is_compressed_not_minified(self) -> None:
		content = b"\x00\x01\x02\x03" * 100
		(self.tmp_path / "data.bin").write_bytes(content)
		response = self.make_app().test_client().get("/static/data.bin", headers={"Accept-Encoding": "gzip"})
		self.assertEqual(response.headers["Content-Encoding"], "gzip")
		self.assertNotIn("X-Flask-Squeeze-Minify", response.headers)
		self.assertEqual(decoded_body(response), content)

	def test_empty_file_stays_empty(self) -> None:
		(self.tmp_path / "empty.js").write_bytes(b"")
		response = self.make_app().test_client().get("/static/empty.js", headers={"Accept-Encoding": "gzip"})
		self.assertEqual(response.status_code, STATUS_OK)
		self.assertEqual(decoded_body(response), b"")

	def test_malformed_css_is_served(self) -> None:
		(self.tmp_path / "malformed.css").write_bytes(b"body { color: #000; /* unclosed comment")
		response = self.make_app().test_client().get("/static/malformed.css", headers={"Accept-Encoding": "gzip"})
		self.assertEqual(response.status_code, STATUS_OK)
		self.assertEqual(response.headers["Content-Length"], str(len(response.data)))

	def test_already_encoded_response_is_preserved(self) -> None:
		response = self.make_app().test_client().get("/already", headers={"Accept-Encoding": "br"})
		self.assertEqual(response.headers["Content-Encoding"], "gzip")
		self.assertEqual(decoded_body(response), CSS)
		self.assertNotIn("X-Flask-Squeeze-Minify", response.headers)

	def test_stream_without_length_is_preserved(self) -> None:
		response = self.make_app().test_client().get("/stream", headers={"Accept-Encoding": "gzip"})
		self.assertEqual(response.data, b"firstsecond")
		self.assertNotIn("Content-Encoding", response.headers)

	def test_non_success_status_is_not_processed(self) -> None:
		client = self.make_app().test_client()
		for status in (204, 304, 404):
			with self.subTest(status=status):
				response = client.get(f"/status/{status}", headers={"Accept-Encoding": "gzip"})
				self.assertEqual(response.status_code, status)
				self.assertNotIn("Content-Encoding", response.headers)
				self.assertNotIn("X-Flask-Squeeze-Minify", response.headers)

	def test_head_has_no_body(self) -> None:
		response = self.make_app().test_client().head("/static/sample.css", headers={"Accept-Encoding": "gzip"})
		self.assertEqual(response.data, b"")

	def test_size_threshold_is_inclusive(self) -> None:
		at_threshold = self.make_app({"SQUEEZE_MIN_SIZE": len(CSS)})
		response = at_threshold.test_client().get("/dynamic.css", headers={"Accept-Encoding": "gzip"})
		self.assertEqual(decoded_body(response), MINIFIED_CSS)
		self.assertEqual(response.headers["Content-Encoding"], "gzip")

		above_threshold = self.make_app({"SQUEEZE_MIN_SIZE": len(CSS) + 1})
		response = above_threshold.test_client().get("/dynamic.css", headers={"Accept-Encoding": "gzip"})
		self.assertEqual(response.data, CSS)
		self.assertNotIn("Content-Encoding", response.headers)

	def test_identity_response_varies_on_encoding(self) -> None:
		response = self.make_app({"SQUEEZE_MINIFY_CSS": False}).test_client().get("/dynamic.css")
		self.assertEqual(response.data, CSS)
		self.assertIn("Accept-Encoding", response.headers["Vary"])

	def test_disabled_squeeze_leaves_response_untouched(self) -> None:
		disabled = {"SQUEEZE_COMPRESS": False, "SQUEEZE_MINIFY_CSS": False, "SQUEEZE_MINIFY_JS": False}
		app = self.make_app({**disabled, "SQUEEZE_MINIFY_HTML": False})
		response = app.test_client().get("/dynamic.css", headers={"Accept-Encoding": "gzip"})
		self.assertEqual(response.data, CSS)
		self.assertNotIn("Vary", response.headers)
		self.assertNotIn("Content-Encoding", response.headers)

	def test_breach_padding_only_on_compressed_dynamic_responses(self) -> None:
		client = self.make_app().test_client()
		first = client.get("/dynamic.css", headers={"Accept-Encoding": "gzip"})
		second = client.get("/dynamic.css", headers={"Accept-Encoding": "gzip"})
		padding = first.headers["X-Flask-Squeeze-Breach-Protection"]
		self.assertGreater(len(padding), 0)
		self.assertNotEqual(padding, second.headers["X-Flask-Squeeze-Breach-Protection"])

		uncompressed = client.get("/dynamic.css")
		self.assertNotIn("X-Flask-Squeeze-Breach-Protection", uncompressed.headers)
		static = client.get("/static/sample.css", headers={"Accept-Encoding": "gzip"})
		self.assertNotIn("X-Flask-Squeeze-Breach-Protection", static.headers)

	def test_compression_levels_per_resource_type(self) -> None:
		paths = {ResourceType.static: "/static/sample.css", ResourceType.dynamic: "/dynamic.css"}
		for encoding, resource_type in itertools.product(Encoding, ResourceType):
			with self.subTest(encoding=encoding, resource_type=resource_type):
				level = 7 if resource_type is ResourceType.static else 3
				client = self.make_app({encoding.level_config_key(resource_type): level}).test_client()
				response = client.get(paths[resource_type], headers={"Accept-Encoding": encoding.value})
				self.assertIn(f"level={level}", response.headers["X-Flask-Squeeze-Compress"])
				self.assertEqual(decoded_body(response), MINIFIED_CSS)

	def test_custom_static_url_path_is_static(self) -> None:
		app = make_sample_app(self.tmp_path, static_url_path="/files")
		response = app.test_client().get("/files/sample.css", headers={"Accept-Encoding": "gzip"})
		self.assertEqual(response.headers["X-Flask-Squeeze-Cache"], "MISS")
		self.assertNotIn("X-Flask-Squeeze-Breach-Protection", response.headers)
		self.assertIn("level=9", response.headers["X-Flask-Squeeze-Compress"])

	def test_blueprint_static_is_static(self) -> None:
		client = self.make_app().test_client()
		response = client.get("/assets/files/sample.css", headers={"Accept-Encoding": "gzip"})
		self.assertEqual(response.headers["X-Flask-Squeeze-Cache"], "MISS")
		self.assertNotIn("X-Flask-Squeeze-Breach-Protection", response.headers)
		self.assertIn("level=9", response.headers["X-Flask-Squeeze-Compress"])
		self.assertEqual(decoded_body(response), MINIFIED_CSS)

	def test_real_world_assets(self) -> None:
		for filename, marker, encoding in (("jquery.js", b"jQuery", "gzip"), ("fomantic.css", b".ui.", "br")):
			with self.subTest(filename=filename):
				source = (FIXTURES_DIR / filename).read_bytes()
				shutil.copy(FIXTURES_DIR / filename, self.tmp_path / filename)
				client = self.make_app().test_client()
				response = client.get(f"/static/{filename}", headers={"Accept-Encoding": encoding})
				self.assertEqual(response.headers["Content-Encoding"], encoding)
				self.assertEqual(response.headers["Content-Length"], str(len(response.data)))
				body = decoded_body(response)
				self.assertLess(len(body), len(source))
				self.assertIn(marker, body)
				minimum_compression_ratio = 2.0
				self.assertGreater(len(source) / len(response.data), minimum_compression_ratio)

	####################################################################################
	#### MARK: Info headers

	def test_info_headers_are_off_by_default(self) -> None:
		client = self.make_app({"SQUEEZE_INFO_HEADERS": False}).test_client()
		for path in ("/static/sample.css", "/static/sample.css", "/dynamic.css"):
			with self.subTest(path=path):
				response = client.get(path, headers={"Accept-Encoding": "gzip"})
				self.assertEqual(response.headers["Content-Encoding"], "gzip")
				for header in INFO_HEADER_NAMES:
					self.assertNotIn(header, response.headers)

	def test_cache_hit_has_the_same_info_headers_as_miss(self) -> None:
		headers = {"Accept-Encoding": "br"}
		client = self.make_app({"SQUEEZE_CACHE_DIR": self.cache_dir}).test_client()
		miss = client.get("/static/sample.css", headers=headers)
		hit = client.get("/static/sample.css", headers=headers)
		restarted = self.make_app({"SQUEEZE_CACHE_DIR": self.cache_dir}).test_client()
		hit_from_disk = restarted.get("/static/sample.css", headers=headers)

		self.assertEqual(miss.headers["X-Flask-Squeeze-Cache"], "MISS")
		for response in (hit, hit_from_disk):
			self.assertEqual(response.headers["X-Flask-Squeeze-Cache"], "HIT")
			for header in ("X-Flask-Squeeze-Minify", "X-Flask-Squeeze-Compress"):
				self.assertEqual(response.headers[header], miss.headers[header])

	def test_skip_reason_is_logged(self) -> None:
		client = self.make_app({"SQUEEZE_MIN_SIZE": len(CSS) + 1}).test_client()
		with self.assertLogs("flask_squeeze", "DEBUG") as logs:
			client.get("/dynamic.css")
		expected = f"GET /dynamic.css: skipped, {len(CSS)} bytes is below SQUEEZE_MIN_SIZE"
		self.assertEqual(logs.output, [f"DEBUG:flask_squeeze.extension:{expected}"])

	####################################################################################
	#### MARK: Ranges and ETags

	def test_range_request_is_not_squeezed(self) -> None:
		client = self.make_app().test_client()
		response = client.get("/static/sample.css", headers={"Accept-Encoding": "gzip", "Range": "bytes=0-3"})
		self.assertEqual(response.status_code, STATUS_PARTIAL_CONTENT)
		self.assertNotIn("Content-Encoding", response.headers)
		self.assertEqual(response.data, CSS[:4])

		full = client.get("/static/sample.css", headers={"Accept-Encoding": "gzip"})
		self.assertEqual(full.headers["X-Flask-Squeeze-Cache"], "MISS")
		self.assertNotIn("Accept-Ranges", full.headers)
		self.assertEqual(decoded_body(full), MINIFIED_CSS)

	def test_each_variant_has_its_own_etag(self) -> None:
		client = self.make_app().test_client()
		responses = {
			encoding: client.get("/static/sample.css", headers={"Accept-Encoding": encoding})
			for encoding in ("", "gzip", "br")
		}
		etags = {encoding: response.headers["ETag"] for encoding, response in responses.items()}
		self.assertEqual(len(set(etags.values())), len(etags))
		for response in responses.values():
			self.assertIn("Last-Modified", response.headers)

		unsqueezed = self.make_app({"SQUEEZE_COMPRESS": False, "SQUEEZE_MINIFY_CSS": False}).test_client()
		original_etag = unsqueezed.get("/static/sample.css").headers["ETag"]
		self.assertNotIn(original_etag, etags.values())

	def test_conditional_request_uses_variant_etag(self) -> None:
		client = self.make_app().test_client()
		gzip_etag = client.get("/static/sample.css", headers={"Accept-Encoding": "gzip"}).headers["ETag"]

		revalidated = client.get("/static/sample.css", headers={"Accept-Encoding": "gzip", "If-None-Match": gzip_etag})
		self.assertEqual(revalidated.status_code, STATUS_NOT_MODIFIED)
		self.assertEqual(revalidated.data, b"")

		other_variant = client.get("/static/sample.css", headers={"Accept-Encoding": "br", "If-None-Match": gzip_etag})
		self.assertEqual(other_variant.status_code, STATUS_OK)
		self.assertEqual(decoded_body(other_variant), MINIFIED_CSS)

	####################################################################################
	#### MARK: Static cache

	def test_static_cache_updates_after_file_change(self) -> None:
		for encoding in Encoding:
			with self.subTest(encoding=encoding):
				(self.tmp_path / "sample.css").write_bytes(CSS)
				client = self.make_app({"SQUEEZE_CACHE_DIR": self.cache_dir / encoding.value}).test_client()
				headers = {"Accept-Encoding": encoding.value}
				first = client.get("/static/sample.css", headers=headers)
				self.assertEqual(first.headers["X-Flask-Squeeze-Cache"], "MISS")
				self.assertEqual(decoded_body(first), MINIFIED_CSS)
				cache_hit = client.get("/static/sample.css", headers=headers)
				self.assertEqual(cache_hit.headers["X-Flask-Squeeze-Cache"], "HIT")
				self.assertEqual(cache_hit.headers["Content-Encoding"], encoding.value)
				self.assertEqual(decoded_body(cache_hit), MINIFIED_CSS)

				(self.tmp_path / "sample.css").write_bytes(b".box { color: blue; }")
				changed = client.get("/static/sample.css", headers=headers)
				self.assertEqual(changed.headers["X-Flask-Squeeze-Cache"], "MISS")
				self.assertEqual(decoded_body(changed), b".box{color:blue}")
				changed_hit = client.get("/static/sample.css", headers=headers)
				self.assertEqual(changed_hit.headers["X-Flask-Squeeze-Cache"], "HIT")

	def test_disk_cache_misses_after_config_change(self) -> None:
		headers = {"Accept-Encoding": "gzip"}
		minified = self.make_app({"SQUEEZE_CACHE_DIR": self.cache_dir}).test_client()
		self.assertEqual(minified.get("/static/sample.css", headers=headers).headers["X-Flask-Squeeze-Cache"], "MISS")

		unminified = self.make_app({"SQUEEZE_CACHE_DIR": self.cache_dir, "SQUEEZE_MINIFY_CSS": False}).test_client()
		response = unminified.get("/static/sample.css", headers=headers)
		self.assertEqual(response.headers["X-Flask-Squeeze-Cache"], "MISS")
		self.assertEqual(decoded_body(response), CSS)

		uncompressed = self.make_app({"SQUEEZE_CACHE_DIR": self.cache_dir, "SQUEEZE_COMPRESS": False}).test_client()
		response = uncompressed.get("/static/sample.css", headers=headers)
		self.assertEqual(response.headers["X-Flask-Squeeze-Cache"], "MISS")
		self.assertNotIn("Content-Encoding", response.headers)

	def test_disk_cache_rejects_corrupt_data(self) -> None:
		first_app = self.make_app({"SQUEEZE_CACHE_DIR": self.cache_dir})
		first = first_app.test_client().get("/static/sample.css", headers={"Accept-Encoding": "gzip"})
		self.assertEqual(first.headers["X-Flask-Squeeze-Cache"], "MISS")
		cache_file = next(self.cache_dir.glob("*.cache"))
		cache_file.write_bytes(b"corrupted")

		restarted = self.make_app({"SQUEEZE_CACHE_DIR": self.cache_dir})
		self.assertEqual(list(self.cache_dir.iterdir()), [])
		response = restarted.test_client().get("/static/sample.css", headers={"Accept-Encoding": "gzip"})
		self.assertEqual(response.headers["X-Flask-Squeeze-Cache"], "MISS")
		self.assertEqual(decoded_body(response), MINIFIED_CSS)
		self.assertEqual(cache_file.read_bytes(), response.data)
		hit = restarted.test_client().get("/static/sample.css", headers={"Accept-Encoding": "gzip"})
		self.assertEqual(hit.headers["X-Flask-Squeeze-Cache"], "HIT")

	def test_distinct_paths_keep_distinct_cache_entries(self) -> None:
		(self.tmp_path / "a_b.css").write_bytes(b".one { color: red; }")
		(self.tmp_path / "a").mkdir()
		(self.tmp_path / "a" / "b.css").write_bytes(b".two { color: blue; }")
		client = self.make_app().test_client()
		headers = {"Accept-Encoding": "gzip"}
		first = client.get("/static/a_b.css", headers=headers)
		second = client.get("/static/a/b.css", headers=headers)
		repeated = client.get("/static/a_b.css", headers=headers)
		self.assertEqual(first.headers["X-Flask-Squeeze-Cache"], "MISS")
		self.assertEqual(second.headers["X-Flask-Squeeze-Cache"], "MISS")
		self.assertEqual(repeated.headers["X-Flask-Squeeze-Cache"], "HIT")
		self.assertEqual(decoded_body(repeated), b".one{color:red}")

	def test_concurrent_static_requests_preserve_content(self) -> None:
		app = self.make_app({"SQUEEZE_CACHE_DIR": self.cache_dir})

		def fetch(_index: int) -> bytes:
			response = app.test_client().get("/static/sample.css", headers={"Accept-Encoding": "gzip"})
			return decoded_body(response)

		with ThreadPoolExecutor(max_workers=8) as executor:
			self.assertEqual(list(executor.map(fetch, range(16))), [MINIFIED_CSS] * 16)

		self.assertEqual(list(self.cache_dir.glob("*.tmp")), [])
		self.assertEqual(len(list(self.cache_dir.glob("*.cache"))), 1)
		self.assertEqual(len(list(self.cache_dir.glob("*.meta"))), 1)

		restarted = self.make_app({"SQUEEZE_CACHE_DIR": self.cache_dir})
		response = restarted.test_client().get("/static/sample.css", headers={"Accept-Encoding": "gzip"})
		self.assertEqual(decoded_body(response), MINIFIED_CSS)

	####################################################################################
	#### MARK: Config

	def test_deferred_init_squeezes_responses(self) -> None:
		squeeze = Squeeze()
		app = Flask(__name__)
		app.config.update(SQUEEZE_MIN_SIZE=0, SQUEEZE_INFO_HEADERS=True)

		@app.get("/dynamic.css")
		def dynamic_css() -> Response:
			return Response(CSS, mimetype="text/css")

		self.assertNotIn("squeeze", app.extensions)
		squeeze.init_app(app)
		response = app.test_client().get("/dynamic.css", headers={"Accept-Encoding": "gzip"})
		self.assertEqual(response.status_code, STATUS_OK)
		self.assertEqual(response.headers["Content-Encoding"], "gzip")
		self.assertEqual(decoded_body(response), MINIFIED_CSS)
		self.assertIn("X-Flask-Squeeze-Minify", response.headers)
		self.assertIn("X-Flask-Squeeze-Compress", response.headers)

	def test_invalid_config_fails_at_init(self) -> None:
		cases: list[tuple[dict[str, object], type[Exception]]] = [
			({"SQUEEZE_LEVEL_BROTLI_STATIC": 12}, ValueError),
			({"SQUEEZE_LEVEL_GZIP_DYNAMIC": -1}, ValueError),
			({"SQUEEZE_LEVEL_GZIP_STATIC": "9"}, TypeError),
			({"SQUEEZE_COMPRESS": "yes"}, TypeError),
			({"SQUEEZE_INFO_HEADERS": 1}, TypeError),
			({"SQUEEZE_CACHE_DIR": 1}, TypeError),
			({"SQUEEZE_MINIFY_JSS": False}, ValueError),
		]
		for config, error in cases:
			with self.subTest(config=config), self.assertRaises(error):
				self.make_app(config)

	def test_init_does_not_write_defaults_into_app_config(self) -> None:
		app = self.make_app()
		self.assertNotIn("SQUEEZE_COMPRESS", app.config)
		self.assertNotIn("SQUEEZE_LEVEL_BROTLI_STATIC", app.config)

	def test_second_init_on_same_app_fails(self) -> None:
		app = self.make_app()
		with self.assertRaises(RuntimeError):
			Squeeze(app)
