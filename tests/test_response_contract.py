from __future__ import annotations

import hashlib
import itertools
import shutil
from base64 import b64encode
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING

from flask import Flask, Response, request, send_file

from flask_squeeze import Squeeze
from flask_squeeze.plan import Encoding, Minification, ResourceType
from tests.sample_app import CSS, HTML, JS, MINIFIED_CSS, SampleAppTestCase, decoded_body, make_sample_app

if TYPE_CHECKING:
	from collections.abc import Mapping

FIXTURES_DIR = Path(__file__).parent / "fixtures"
INFO_HEADER_NAMES = ("X-Flask-Squeeze-Minify", "X-Flask-Squeeze-Compress", "X-Flask-Squeeze-Cache")
LOG_PREFIX = "DEBUG:flask_squeeze.extension:"


@dataclass(frozen=True)
class AssetCase:
	file_extension: str
	source: bytes
	minified: bytes


ASSET_CASES = [
	AssetCase("css", CSS, MINIFIED_CSS),
	AssetCase("js", JS, b"const answer=42"),
	AssetCase("html", HTML, b"<p>Hello</p>"),
]


def make_css_app(config: Mapping[str, object]) -> Flask:
	"""App with one dynamic CSS route and Flask-Squeeze not yet initialized."""
	app = Flask(__name__)
	app.config.update(SQUEEZE_MIN_SIZE=0, SQUEEZE_INFO_HEADERS=True)
	app.config.update(config)

	@app.get("/dynamic.css")
	def dynamic_css() -> Response:
		return Response(CSS, mimetype="text/css")

	return app


class BodyAndHeadersTest(SampleAppTestCase):
	def test_response_body_contract(self) -> None:
		for static, asset, minify, encoding in itertools.product(
			(False, True), ASSET_CASES, (False, True), ("", "gzip", "deflate", "br")
		):
			with self.subTest(static=static, asset=asset.file_extension, minify=minify, encoding=encoding):
				self.check_response_body_contract(encoding, asset, minify=minify, static=static)

	def check_response_body_contract(self, encoding: str, asset: AssetCase, *, minify: bool, static: bool) -> None:
		app = self.make_app({"SQUEEZE_MINIFY_CSS": minify, "SQUEEZE_MINIFY_JS": minify, "SQUEEZE_MINIFY_HTML": minify})
		path = f"/static/sample.{asset.file_extension}" if static else f"/dynamic.{asset.file_extension}"
		response = app.test_client().get(path, headers={"Accept-Encoding": encoding})
		self.assertEqual(response.status_code, HTTPStatus.OK)
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

	def test_head_has_the_headers_of_get(self) -> None:
		client = self.make_app().test_client()
		for path in ("/static/sample.css", "/dynamic.css"):
			with self.subTest(path=path):
				get = client.get(path, headers={"Accept-Encoding": "br"})
				head = client.head(path, headers={"Accept-Encoding": "br"})
				self.assertEqual(head.data, b"")
				for header in ("Content-Length", "Content-Encoding", "ETag", "Vary"):
					self.assertEqual(head.headers.get(header), get.headers.get(header), header)

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
		self.assertEqual(response.status_code, HTTPStatus.OK)
		self.assertEqual(decoded_body(response), b"")

	def test_malformed_css_is_served(self) -> None:
		(self.tmp_path / "malformed.css").write_bytes(b"body { color: #000; /* unclosed comment")
		response = self.make_app().test_client().get("/static/malformed.css", headers={"Accept-Encoding": "gzip"})
		self.assertEqual(response.status_code, HTTPStatus.OK)
		self.assertEqual(response.headers["Content-Length"], str(len(response.data)))

	def test_other_charsets_are_compressed_not_minified(self) -> None:
		source = ".a { content: '\N{LATIN SMALL LETTER E WITH ACUTE}'; }".encode("latin-1")
		app = self.make_app()

		@app.get("/latin1.css")
		def latin1_css() -> Response:
			return Response(source, content_type="text/css; charset=iso-8859-1")

		response = app.test_client().get("/latin1.css", headers={"Accept-Encoding": "gzip"})
		self.assertEqual(response.headers["Content-Encoding"], "gzip")
		self.assertNotIn("X-Flask-Squeeze-Minify", response.headers)
		self.assertEqual(decoded_body(response), source)

	def test_invalid_utf8_declared_as_utf8_raises(self) -> None:
		app = self.make_app()

		@app.get("/latin1.css")
		def latin1_css() -> Response:
			# Flask declares charset=utf-8 for text mimetypes
			return Response("\N{LATIN SMALL LETTER E WITH ACUTE}".encode("latin-1"), mimetype="text/css")

		with self.assertRaises(UnicodeDecodeError):
			app.test_client().get("/latin1.css")

	def test_already_encoded_response_is_preserved(self) -> None:
		response = self.make_app().test_client().get("/already", headers={"Accept-Encoding": "br"})
		self.assertEqual(response.headers["Content-Encoding"], "gzip")
		self.assertEqual(decoded_body(response), CSS)
		self.assertNotIn("X-Flask-Squeeze-Minify", response.headers)

	def test_stream_without_length_is_preserved(self) -> None:
		response = self.make_app().test_client().get("/stream", headers={"Accept-Encoding": "gzip"})
		self.assertEqual(response.data, b"firstsecond")
		self.assertNotIn("Content-Encoding", response.headers)

	def test_offloaded_files_keep_their_original_representation(self) -> None:
		client = self.make_app({"USE_X_SENDFILE": True, "SQUEEZE_CACHE_DIR": self.cache_dir}).test_client()
		for method in ("GET", "HEAD"):
			with self.subTest(method=method):
				response = client.open("/static/sample.css", method=method, headers={"Accept-Encoding": "gzip"})
				self.assertEqual(response.data, b"")
				self.assertEqual(response.headers["X-Sendfile"], str(self.tmp_path / "sample.css"))
				self.assertEqual(response.content_length, len(CSS))
				self.assertNotIn("Content-Encoding", response.headers)
				self.assertNotIn("Vary", response.headers)
				for header in INFO_HEADER_NAMES:
					self.assertNotIn(header, response.headers)

		etag = client.get("/static/sample.css").headers["ETag"]
		revalidated = client.get("/static/sample.css", headers={"Accept-Encoding": "gzip", "If-None-Match": etag})
		self.assertEqual(revalidated.status_code, HTTPStatus.NOT_MODIFIED)
		self.assertEqual(revalidated.data, b"")
		self.assertNotIn("Content-Encoding", revalidated.headers)
		self.assertEqual(list(self.cache_dir.iterdir()), [])

	def test_unsqueezable_statuses_are_untouched(self) -> None:
		client = self.make_app().test_client()
		statuses = (
			HTTPStatus.NO_CONTENT,
			HTTPStatus.RESET_CONTENT,
			HTTPStatus.MOVED_PERMANENTLY,
			HTTPStatus.NOT_MODIFIED,
			HTTPStatus.PRECONDITION_FAILED,
			HTTPStatus.NOT_FOUND,
			HTTPStatus.INTERNAL_SERVER_ERROR,
		)
		for status in statuses:
			with self.subTest(status=status):
				response = client.get(f"/status/{status.value}", headers={"Accept-Encoding": "gzip"})
				self.assertEqual(response.status_code, status)
				self.assertNotIn("Content-Encoding", response.headers)
				self.assertNotIn("Vary", response.headers)

	def test_other_success_statuses_are_squeezed(self) -> None:
		client = self.make_app().test_client()
		for status in (HTTPStatus.CREATED, HTTPStatus.ACCEPTED, HTTPStatus.NON_AUTHORITATIVE_INFORMATION):
			with self.subTest(status=status):
				response = client.get(f"/status/{status.value}", headers={"Accept-Encoding": "gzip"})
				self.assertEqual(response.status_code, status)
				self.assertEqual(response.headers["Content-Encoding"], "gzip")
				self.assertEqual(decoded_body(response), b"payload")

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

	def test_explicit_identity_preference_still_allows_minification(self) -> None:
		response = (
			self.make_app().test_client().get("/dynamic.css", headers={"Accept-Encoding": "identity;q=1, gzip;q=0.1"})
		)
		self.assertEqual(response.status_code, HTTPStatus.OK)
		self.assertEqual(response.data, MINIFIED_CSS)
		self.assertNotIn("Content-Encoding", response.headers)
		self.assertIn("Accept-Encoding", response.headers["Vary"])

	def test_rejected_encodings_return_an_empty_406(self) -> None:
		client = self.make_app().test_client()
		for path, method, encoding in itertools.product(
			("/dynamic.css", "/static/sample.css"), ("GET", "HEAD"), ("identity;q=0, *;q=0", "*;q=0")
		):
			with self.subTest(path=path, method=method, encoding=encoding):
				response = client.open(path, method=method, headers={"Accept-Encoding": encoding})
				self.assertEqual(response.status_code, HTTPStatus.NOT_ACCEPTABLE)
				self.assertEqual(response.data, b"")
				self.assertNotIn("Content-Encoding", response.headers)
				self.assertNotIn("ETag", response.headers)
				self.assertIn("Accept-Encoding", response.headers["Vary"])
				for header in INFO_HEADER_NAMES:
					self.assertNotIn(header, response.headers)

	def test_identity_rejection_when_compression_is_unavailable(self) -> None:
		for config in ({"SQUEEZE_COMPRESS": False}, {"SQUEEZE_MIN_SIZE": len(CSS) + 1}):
			with self.subTest(config=config):
				response = (
					self.make_app(config)
					.test_client()
					.get("/dynamic.css", headers={"Accept-Encoding": "gzip, identity;q=0"})
				)
				self.assertEqual(response.status_code, HTTPStatus.NOT_ACCEPTABLE)
				self.assertEqual(response.data, b"")

	def test_integrity_metadata_preserves_original_representation(self) -> None:
		digest = b64encode(hashlib.sha256(CSS).digest()).decode("ascii")
		cases = (
			("Content-Digest", f"sha-256=:{digest}:"),
			("Repr-Digest", f"sha-256=:{digest}:"),
			("Digest", f"sha-256={digest}"),
			("Content-MD5", "application-provided"),
			("Signature", "sig1=:application-provided:"),
			("Signature-Input", 'sig1=("content-length" "vary")'),
		)

		def make_integrity_app(header: str, value: str) -> Flask:
			app = self.make_app({"SQUEEZE_CACHE_DIR": self.cache_dir})

			@app.after_request
			def add_integrity(response: Response) -> Response:
				response.headers[header] = value
				return response

			return app

		for (header, value), path, method in itertools.product(
			cases, ("/dynamic.css", "/static/sample.css"), ("GET", "HEAD")
		):
			with self.subTest(header=header, path=path, method=method):
				response = (
					make_integrity_app(header, value)
					.test_client()
					.open(path, method=method, headers={"Accept-Encoding": "gzip"})
				)
				self.assertEqual(response.status_code, HTTPStatus.OK)
				self.assertEqual(response.data, CSS if method == "GET" else b"")
				self.assertEqual(response.headers[header], value)
				self.assertEqual(response.content_length, len(CSS))
				self.assertNotIn("Content-Encoding", response.headers)
				self.assertNotIn("Vary", response.headers)
				for info_header in INFO_HEADER_NAMES:
					self.assertNotIn(info_header, response.headers)
		self.assertEqual(list(self.cache_dir.iterdir()), [])

	def test_existing_vary_is_kept(self) -> None:
		app = self.make_app()

		@app.get("/vary-cookie.css")
		def vary_cookie() -> Response:
			response = Response(CSS, mimetype="text/css")
			response.vary.add("Cookie")
			return response

		response = app.test_client().get("/vary-cookie.css", headers={"Accept-Encoding": "gzip"})
		self.assertEqual(response.headers["Vary"], "Cookie, Accept-Encoding")

	def test_minify_only_does_not_vary(self) -> None:
		client = self.make_app({"SQUEEZE_COMPRESS": False}).test_client()
		response = client.get("/dynamic.css", headers={"Accept-Encoding": "gzip"})
		self.assertEqual(response.data, MINIFIED_CSS)
		self.assertNotIn("Vary", response.headers)
		self.assertNotIn("X-Flask-Squeeze-Breach-Protection", response.headers)

	def test_disabled_squeeze_leaves_response_untouched(self) -> None:
		disabled = {"SQUEEZE_COMPRESS": False, "SQUEEZE_MINIFY_CSS": False, "SQUEEZE_MINIFY_JS": False}
		app = self.make_app({**disabled, "SQUEEZE_MINIFY_HTML": False})
		self.assertEqual(app.after_request_funcs[None], [])
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

	def test_file_sent_by_a_view_is_dynamic(self) -> None:
		app = self.make_app()

		@app.get("/download.css")
		def download() -> Response:
			return send_file(self.tmp_path / "sample.css")

		client = app.test_client()
		response = client.get("/download.css", headers={"Accept-Encoding": "gzip"})
		self.assertEqual(decoded_body(response), MINIFIED_CSS)
		self.assertIn("level=1", response.headers["X-Flask-Squeeze-Compress"])
		self.assertIn("X-Flask-Squeeze-Breach-Protection", response.headers)
		self.assertNotIn("X-Flask-Squeeze-Cache", response.headers)

		headers = {"Accept-Encoding": "gzip", "If-None-Match": response.headers["ETag"]}
		self.assertEqual(client.get("/download.css", headers=headers).status_code, HTTPStatus.NOT_MODIFIED)

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


class InfoHeadersAndLoggingTest(SampleAppTestCase):
	def test_info_headers_can_be_disabled(self) -> None:
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

	def test_skip_reasons_are_logged(self) -> None:
		above_css_size = {"SQUEEZE_MIN_SIZE": len(CSS) + 1}
		cases: list[tuple[Mapping[str, object], str, str]] = [
			({}, "/stream", "skipped, content length unknown"),
			({}, "/status/404", "skipped, status code 404"),
			(above_css_size, "/dynamic.css", f"skipped, {len(CSS)} bytes is below SQUEEZE_MIN_SIZE"),
			({}, "/already", "skipped, response already encoded"),
			({}, "/json", "skipped, no compression or minification applicable"),
		]
		for config, path, message in cases:
			with self.subTest(path=path):
				client = self.make_app(config).test_client()
				with self.assertLogs("flask_squeeze", "DEBUG") as logs:
					client.get(path)
				self.assertEqual(logs.output, [f"{LOG_PREFIX}GET {path}: {message}"])

	def test_static_cache_status_is_logged(self) -> None:
		client = self.make_app().test_client()
		with self.assertLogs("flask_squeeze", "DEBUG") as miss_logs:
			client.get("/static/sample.css", headers={"Accept-Encoding": "gzip"})
		with self.assertLogs("flask_squeeze", "DEBUG") as hit_logs:
			client.get("/static/sample.css", headers={"Accept-Encoding": "gzip"})
		self.assertIn(f"{LOG_PREFIX}GET /static/sample.css: static cache miss, squeezing", miss_logs.output)
		self.assertIn(f"{LOG_PREFIX}GET /static/sample.css: static cache hit", hit_logs.output)

	def test_nothing_is_logged_above_debug(self) -> None:
		client = self.make_app().test_client()
		with self.assertNoLogs("flask_squeeze", "INFO"):
			for path in ("/static/sample.css", "/static/sample.css", "/dynamic.css", "/stream", "/json"):
				client.get(path, headers={"Accept-Encoding": "gzip"})


class ConditionalRequestTest(SampleAppTestCase):
	def test_explicit_file_error_statuses_are_preserved(self) -> None:
		app = self.make_app()

		@app.get("/file-status/<int:code>")
		def file_status(code: int) -> Response:
			response = send_file(self.tmp_path / "sample.css")
			response.status_code = code
			return response

		client = app.test_client()
		original_etag = (
			self.make_app({"SQUEEZE_COMPRESS": False, "SQUEEZE_MINIFY_CSS": False})
			.test_client()
			.get("/static/sample.css")
			.headers["ETag"]
		)
		cases: tuple[tuple[HTTPStatus, dict[str, str]], ...] = (
			(HTTPStatus.NOT_MODIFIED, {}),
			(HTTPStatus.PRECONDITION_FAILED, {}),
			(HTTPStatus.NOT_MODIFIED, {"If-None-Match": '"different"'}),
			(HTTPStatus.PRECONDITION_FAILED, {"If-Match": original_etag}),
		)
		for status, conditions in cases:
			with self.subTest(status=status, conditions=conditions):
				response = client.get(f"/file-status/{status.value}", headers={"Accept-Encoding": "gzip", **conditions})
				self.assertEqual(response.status_code, status)
				self.assertEqual(response.headers["ETag"], original_etag)
				self.assertNotIn("Content-Encoding", response.headers)
				self.assertNotIn("Vary", response.headers)

	def test_range_request_is_not_squeezed(self) -> None:
		client = self.make_app().test_client()
		response = client.get("/static/sample.css", headers={"Accept-Encoding": "gzip", "Range": "bytes=0-3"})
		self.assertEqual(response.status_code, HTTPStatus.PARTIAL_CONTENT)
		self.assertNotIn("Content-Encoding", response.headers)
		self.assertEqual(response.data, CSS[:4])

		full = client.get("/static/sample.css", headers={"Accept-Encoding": "gzip"})
		self.assertEqual(full.headers["X-Flask-Squeeze-Cache"], "MISS")
		self.assertNotIn("Accept-Ranges", full.headers)
		self.assertEqual(decoded_body(full), MINIFIED_CSS)

	def test_if_range_with_variant_etag_gets_the_full_variant(self) -> None:
		client = self.make_app().test_client()
		etag = client.get("/static/sample.css", headers={"Accept-Encoding": "gzip"}).headers["ETag"]
		response = client.get(
			"/static/sample.css", headers={"Accept-Encoding": "gzip", "Range": "bytes=0-3", "If-Range": etag}
		)
		self.assertEqual(response.status_code, HTTPStatus.OK)
		self.assertEqual(decoded_body(response), MINIFIED_CSS)

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

	def test_static_variant_is_identical_across_app_instances(self) -> None:
		# Variant ETags are strong, so workers that squeeze the same file must produce the same bytes
		for encoding in Encoding:
			with self.subTest(encoding=encoding):
				headers = {"Accept-Encoding": encoding.value}
				first = self.make_app().test_client().get("/static/sample.css", headers=headers)
				second = self.make_app().test_client().get("/static/sample.css", headers=headers)
				self.assertEqual(first.headers["ETag"], second.headers["ETag"])
				self.assertEqual(first.data, second.data)

	def test_weak_etag_stays_weak(self) -> None:
		app = self.make_app()

		@app.get("/weak.css")
		def weak_etag() -> Response:
			response = send_file(self.tmp_path / "sample.css")
			response.set_etag("v1", weak=True)
			return response

		response = app.test_client().get("/weak.css", headers={"Accept-Encoding": "gzip"})
		self.assertEqual(response.get_etag(), (hashlib.sha256(response.data).hexdigest(), True))

	def test_strong_etag_tracks_served_bytes_even_when_source_etag_is_unchanged(self) -> None:
		app = self.make_app()
		bodies = (CSS, b".box { color: blue; }")

		@app.get("/versioned.css")
		def versioned_css() -> Response:
			return send_file(self.tmp_path / "sample.css", etag="v1")

		client = app.test_client()
		first = client.get("/versioned.css", headers={"Accept-Encoding": "gzip"})
		(self.tmp_path / "sample.css").write_bytes(bodies[1])
		second = client.get("/versioned.css", headers={"Accept-Encoding": "gzip"})
		self.assertNotEqual(first.headers["ETag"], second.headers["ETag"])
		for response in (first, second):
			self.assertEqual(response.get_etag(), (hashlib.sha256(response.data).hexdigest(), False))

	def test_dynamic_application_etags_and_conditions_are_preserved(self) -> None:
		app = self.make_app()

		@app.get("/conditional/<int:weak>.css")
		def conditional_css(weak: int) -> Response:
			response = Response(CSS, mimetype="text/css")
			response.set_etag("source", weak=bool(weak))
			response.make_conditional(request)
			return response

		client = app.test_client()
		for weak, method in itertools.product((False, True), ("GET", "HEAD")):
			with self.subTest(weak=weak, method=method):
				path = f"/conditional/{int(weak)}.css"
				full = client.open(path, method=method, headers={"Accept-Encoding": "gzip"})
				self.assertEqual(full.status_code, HTTPStatus.OK)
				self.assertEqual(full.get_etag(), ("source", weak))
				self.assertEqual(full.data, CSS if method == "GET" else b"")
				self.assertNotIn("Content-Encoding", full.headers)
				self.assertNotIn("Vary", full.headers)
				conditions = (
					("If-None-Match", full.headers["ETag"], HTTPStatus.NOT_MODIFIED),
					("If-Match", '"source"', HTTPStatus.OK),
					("If-Match", '"different"', HTTPStatus.PRECONDITION_FAILED),
				)
				for header, value, status in conditions:
					response = client.open(path, method=method, headers={"Accept-Encoding": "gzip", header: value})
					self.assertEqual(response.status_code, status)
					self.assertEqual(response.headers["ETag"], full.headers["ETag"])
					self.assertNotIn("Content-Encoding", response.headers)
					for info_header in INFO_HEADER_NAMES:
						self.assertNotIn(info_header, response.headers)

	def test_conditional_request_uses_variant_etag(self) -> None:
		client = self.make_app().test_client()
		gzip_etag = client.get("/static/sample.css", headers={"Accept-Encoding": "gzip"}).headers["ETag"]

		revalidated = client.get("/static/sample.css", headers={"Accept-Encoding": "gzip", "If-None-Match": gzip_etag})
		self.assertEqual(revalidated.status_code, HTTPStatus.NOT_MODIFIED)
		self.assertEqual(revalidated.data, b"")

		other_variant = client.get("/static/sample.css", headers={"Accept-Encoding": "br", "If-None-Match": gzip_etag})
		self.assertEqual(other_variant.status_code, HTTPStatus.OK)
		self.assertEqual(decoded_body(other_variant), MINIFIED_CSS)

	def test_file_conditional_requests_are_answered_for_the_variant(self) -> None:
		app = self.make_app()

		@app.get("/download.css")
		def download() -> Response:
			return send_file(self.tmp_path / "sample.css")

		client = app.test_client()
		unsqueezed = self.make_app({"SQUEEZE_COMPRESS": False, "SQUEEZE_MINIFY_CSS": False}).test_client()
		original_etag = unsqueezed.get("/static/sample.css").headers["ETag"]
		for path, method in itertools.product(("/static/sample.css", "/download.css"), ("GET", "HEAD")):
			full = client.get(path, headers={"Accept-Encoding": "gzip"})
			variant_etag = full.headers["ETag"]
			cases = [
				("If-Modified-Since", full.headers["Last-Modified"], HTTPStatus.NOT_MODIFIED, b""),
				("If-None-Match", variant_etag, HTTPStatus.NOT_MODIFIED, b""),
				("If-None-Match", "*", HTTPStatus.NOT_MODIFIED, b""),
				("If-None-Match", original_etag, HTTPStatus.OK, MINIFIED_CSS),
				("If-Match", variant_etag, HTTPStatus.OK, MINIFIED_CSS),
				("If-Match", original_etag, HTTPStatus.PRECONDITION_FAILED, MINIFIED_CSS),
			]
			for header, value, expected_status, expected_body in cases:
				with self.subTest(path=path, method=method, header=header, value=value):
					response = client.open(path, method=method, headers={"Accept-Encoding": "gzip", header: value})
					self.assertEqual(response.status_code, expected_status)
					self.assertEqual(response.headers["ETag"], variant_etag)
					self.assertIn("Accept-Encoding", response.headers["Vary"])
					if method == "HEAD":
						self.assertEqual(response.data, b"")
					else:
						self.assertEqual(decoded_body(response), expected_body)

	def test_unsqueezed_static_conditional_answer_is_kept(self) -> None:
		(self.tmp_path / "image.png").write_bytes(b"\x89PNG" + bytes(100))
		client = self.make_app().test_client()
		etag = client.get("/static/image.png").headers["ETag"]
		revalidated = client.get("/static/image.png", headers={"If-None-Match": etag})
		self.assertEqual(revalidated.status_code, HTTPStatus.NOT_MODIFIED)
		self.assertEqual(revalidated.headers["ETag"], etag)


class StaticCacheTest(SampleAppTestCase):
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
		self.assertEqual(list(self.cache_dir.glob("*.meta")), [])

		restarted = self.make_app({"SQUEEZE_CACHE_DIR": self.cache_dir})
		response = restarted.test_client().get("/static/sample.css", headers={"Accept-Encoding": "gzip"})
		self.assertEqual(decoded_body(response), MINIFIED_CSS)


class InitTest(SampleAppTestCase):
	def test_disabled_squeeze_does_not_access_cache_paths(self) -> None:
		unusable_path = self.tmp_path / "not-a-directory"
		unusable_path.write_bytes(b"untouched")
		for cache_dir in (unusable_path, self.cache_dir):
			with self.subTest(cache_dir=cache_dir):
				app = self.make_app(
					{
						"SQUEEZE_COMPRESS": False,
						**{minification.enable_config_key: False for minification in Minification},
						"SQUEEZE_CACHE_DIR": cache_dir,
					}
				)
				self.assertIn("squeeze", app.extensions)
				self.assertEqual(app.after_request_funcs[None], [])
				with self.assertRaisesRegex(RuntimeError, "already initialized"):
					Squeeze(app)
		self.assertEqual(unusable_path.read_bytes(), b"untouched")
		self.assertFalse(self.cache_dir.exists())

	def test_disabled_squeeze_keeps_incompatible_cache_files(self) -> None:
		self.cache_dir.mkdir()
		cache_file = self.cache_dir / "incompatible.cache"
		cache_file.write_bytes(b"untouched")
		self.make_app(
			{
				"SQUEEZE_COMPRESS": False,
				**{minification.enable_config_key: False for minification in Minification},
				"SQUEEZE_CACHE_DIR": self.cache_dir,
			}
		)
		self.assertEqual(cache_file.read_bytes(), b"untouched")

	def test_deferred_init_squeezes_responses(self) -> None:
		squeeze = Squeeze()
		app = make_css_app({})
		self.assertNotIn("squeeze", app.extensions)
		squeeze.init_app(app)
		response = app.test_client().get("/dynamic.css", headers={"Accept-Encoding": "gzip"})
		self.assertEqual(response.status_code, HTTPStatus.OK)
		self.assertEqual(response.headers["Content-Encoding"], "gzip")
		self.assertEqual(decoded_body(response), MINIFIED_CSS)
		self.assertIn("X-Flask-Squeeze-Minify", response.headers)
		self.assertIn("X-Flask-Squeeze-Compress", response.headers)

	def test_one_instance_initializes_apps_with_their_own_config(self) -> None:
		squeeze = Squeeze()
		compressing = make_css_app({})
		minifying = make_css_app({"SQUEEZE_COMPRESS": False})
		squeeze.init_app(compressing)
		squeeze.init_app(minifying)

		compressed = compressing.test_client().get("/dynamic.css", headers={"Accept-Encoding": "gzip"})
		self.assertEqual(compressed.headers["Content-Encoding"], "gzip")
		self.assertEqual(decoded_body(compressed), MINIFIED_CSS)
		minified = minifying.test_client().get("/dynamic.css", headers={"Accept-Encoding": "gzip"})
		self.assertNotIn("Content-Encoding", minified.headers)
		self.assertEqual(minified.data, MINIFIED_CSS)

	def test_invalid_config_fails_at_init(self) -> None:
		with self.assertRaisesRegex(ValueError, "SQUEEZE_MINIFY_JSS"):
			self.make_app({"SQUEEZE_MINIFY_JSS": False})

	def test_init_does_not_write_defaults_into_app_config(self) -> None:
		app = self.make_app()
		self.assertNotIn("SQUEEZE_COMPRESS", app.config)
		self.assertNotIn("SQUEEZE_LEVEL_BROTLI_STATIC", app.config)

	def test_second_init_on_same_app_fails(self) -> None:
		app = self.make_app()
		with self.assertRaisesRegex(RuntimeError, "already initialized"):
			Squeeze(app)
