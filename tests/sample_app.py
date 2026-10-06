from __future__ import annotations

import gzip
import tempfile
import unittest
import zlib
from pathlib import Path
from typing import TYPE_CHECKING

import brotli
from flask import Blueprint, Flask, Response, render_template_string
from typing_extensions import override

from flask_squeeze import Squeeze
from flask_squeeze.plan import Encoding
from tests.buffered_client import BufferedTestClient

if TYPE_CHECKING:
	from collections.abc import Mapping

	from werkzeug.wrappers import Response as WerkzeugResponse

CSS = b".box { color: red; margin: 0px; font-family: " + b"x" * 100 + b"; }"
JS = b"const answer = '" + b"x" * 100 + b"'; // comment\n"
HTML = b"<p>Hello</p><!-- comment -->" * 10
MINIFIED_CSS = b".box{color:red;margin:0;font-family:" + b"x" * 100 + b"}"
PAGE_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
	<style>
		.some-test-class {
			color: red;
		}
	</style>
</head>
<body>
	<p>{{ text }}</p>
	<script>
		function someTestFunction() {
			console.log("test");
		}
	</script>
</body>
</html>
"""


def write_sample_assets(static_dir: Path) -> None:
	(static_dir / "sample.css").write_bytes(CSS)
	(static_dir / "sample.js").write_bytes(JS)
	(static_dir / "sample.html").write_bytes(HTML)
	blueprint_static_dir = static_dir / "blueprint"
	blueprint_static_dir.mkdir(exist_ok=True)
	(blueprint_static_dir / "sample.css").write_bytes(CSS)


def make_sample_app(
	static_dir: Path,
	config: Mapping[str, object] | None = None,
	static_url_path: str = "/static",
) -> Flask:
	"""App serving the assets of `write_sample_assets` from `static_dir`."""
	app = Flask(__name__, static_folder=str(static_dir), static_url_path=static_url_path)
	app.config.update(SQUEEZE_MIN_SIZE=0, SQUEEZE_INFO_HEADERS=True)
	app.config.update(config or {})

	@app.get("/")
	def rendered_page() -> str:
		return render_template_string(PAGE_TEMPLATE, text="Hello")

	@app.get("/dynamic.css")
	def dynamic_css() -> Response:
		return Response(CSS, mimetype="text/css")

	@app.get("/dynamic.js")
	def dynamic_js() -> Response:
		return Response(JS, mimetype="text/javascript")

	@app.get("/dynamic.html")
	def dynamic_html() -> Response:
		return Response(HTML, mimetype="text/html")

	@app.get("/json")
	def json_response() -> Response:
		return Response(b"[1, 2, 3]", mimetype="application/json")

	@app.get("/already")
	def already_encoded() -> Response:
		return Response(gzip.compress(CSS), mimetype="text/css", headers={"Content-Encoding": "gzip"})

	@app.get("/stream")
	def streamed() -> Response:
		return Response((chunk for chunk in (b"first", b"second")), mimetype="text/plain")

	@app.get("/status/<int:code>")
	def status_response(code: int) -> Response:
		return Response(b"payload", status=code, mimetype="text/plain")

	blueprint = Blueprint("assets", __name__, static_folder=str(static_dir / "blueprint"), static_url_path="/files")
	app.register_blueprint(blueprint, url_prefix="/assets")

	Squeeze(app)
	app.testing = True
	app.test_client_class = BufferedTestClient
	return app


def decompress(body: bytes, encoding: Encoding) -> bytes:
	match encoding:
		case Encoding.gzip:
			return gzip.decompress(body)
		case Encoding.deflate:
			return zlib.decompress(body)
		case Encoding.br:
			decoded = brotli.decompress(body)
			if not isinstance(decoded, bytes):
				msg = f"brotli returned {type(decoded)}, expected bytes"
				raise TypeError(msg)
			return decoded


def decoded_body(response: WerkzeugResponse) -> bytes:
	body: bytes = response.data
	content_encoding = response.headers.get("Content-Encoding")
	if content_encoding is None:
		return body
	return decompress(body, Encoding(content_encoding))


class SampleAppTestCase(unittest.TestCase):
	"""Serves the sample assets from a fresh temporary directory per test."""

	@override
	def setUp(self) -> None:
		self.tmp_path = Path(self.enterContext(tempfile.TemporaryDirectory()))
		self.cache_dir = self.tmp_path / "cache"
		write_sample_assets(self.tmp_path)

	def make_app(self, config: Mapping[str, object] | None = None) -> Flask:
		return make_sample_app(self.tmp_path, config)
