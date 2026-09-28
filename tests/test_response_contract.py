from __future__ import annotations

import gzip
import zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING

import brotli
import pytest
from flask import Flask, Response

from flask_squeeze import Squeeze

if TYPE_CHECKING:
	from pathlib import Path

	from werkzeug.wrappers import Response as WerkzeugResponse

CSS = b".box { color: red; margin: 0px; }"
JS = b"const answer = 42; // comment\n"
HTML = b"<p>Hello</p><!-- comment -->"
STATUS_OK = 200


@dataclass(frozen=True)
class AssetCase:
	kind: str
	source: bytes
	minified: bytes


def make_app(static_dir: Path, cache_dir: Path | None = None) -> Flask:
	app = Flask(__name__, static_folder=str(static_dir), static_url_path="/static")
	app.config.update(SQUEEZE_MIN_SIZE=0, SQUEEZE_CACHE_DIR=cache_dir)
	(static_dir / "sample.css").write_bytes(CSS)
	(static_dir / "sample.js").write_bytes(JS)
	(static_dir / "sample.html").write_bytes(HTML)

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

	Squeeze(app)
	app.testing = True
	return app


@pytest.fixture
def app(tmp_path: Path) -> Flask:
	return make_app(tmp_path)


def decoded_body(response: WerkzeugResponse) -> bytes:
	body = bytes(response.data)
	encoding = response.headers.get("Content-Encoding")
	if encoding == "gzip":
		return gzip.decompress(body)
	if encoding == "deflate":
		return zlib.decompress(body)
	if encoding == "br":
		decoded = brotli.decompress(body)
		assert isinstance(decoded, bytes)
		return decoded
	return body


@pytest.mark.parametrize("encoding", ["", "gzip", "deflate", "br"])
@pytest.mark.parametrize("minify", [False, True])
@pytest.mark.parametrize(
	"asset",
	[
		AssetCase("css", CSS, b".box{color:red;margin:0}"),
		AssetCase("js", JS, b"const answer=42"),
		AssetCase("html", HTML, b"<p>Hello"),
	],
)
@pytest.mark.parametrize("static", [False, True])
def test_response_body_contract(
	app: Flask,
	encoding: str,
	minify: bool,
	asset: AssetCase,
	static: bool,
) -> None:
	app.config.update(
		SQUEEZE_MINIFY_CSS=minify,
		SQUEEZE_MINIFY_JS=minify,
		SQUEEZE_MINIFY_HTML=minify,
	)
	path = f"/static/sample.{asset.kind}" if static else f"/dynamic.{asset.kind}"
	response = app.test_client().get(path, headers={"Accept-Encoding": encoding})
	assert response.status_code == STATUS_OK
	assert response.headers["Content-Length"] == str(len(response.data))
	assert response.headers.get("Content-Encoding", "") == encoding
	assert ("X-Flask-Squeeze-Minify" in response.headers) is minify
	assert ("X-Flask-Squeeze-Compress" in response.headers) is bool(encoding)
	assert "Accept-Encoding" in response.headers.get("Vary", "")

	assert decoded_body(response) == (asset.minified if minify else asset.source)


@pytest.mark.parametrize(
	("accepted", "expected"),
	[
		("gzip;q=0", ""),
		("br;q=0, gzip;q=1", "gzip"),
		("gzip;q=0.5, br;q=0.8", "br"),
		("gzip;q=0.8, br;q=0.5", "gzip"),
		("*;q=0.5", "br"),
		("gzip;q=0, *;q=0.5", "br"),
		("xgzip", ""),
	],
)
def test_accept_encoding_quality(app: Flask, accepted: str, expected: str) -> None:
	app.config["SQUEEZE_MINIFY_CSS"] = False
	response = app.test_client().get("/static/sample.css", headers={"Accept-Encoding": accepted})
	assert response.headers.get("Content-Encoding", "") == expected
	assert decoded_body(response) == CSS


def test_json_is_data_not_javascript(app: Flask) -> None:
	response = app.test_client().get("/json")
	assert response.data == b"[1, 2, 3]"
	assert "X-Flask-Squeeze-Minify" not in response.headers


def test_already_encoded_response_is_preserved(app: Flask) -> None:
	response = app.test_client().get("/already", headers={"Accept-Encoding": "br"})
	assert response.headers["Content-Encoding"] == "gzip"
	assert decoded_body(response) == CSS
	assert "X-Flask-Squeeze-Minify" not in response.headers


def test_stream_without_length_is_preserved(app: Flask) -> None:
	response = app.test_client().get("/stream", headers={"Accept-Encoding": "gzip"})
	assert response.data == b"firstsecond"
	assert "Content-Encoding" not in response.headers


@pytest.mark.parametrize("status", [204, 304, 404])
def test_non_success_status_is_not_processed(app: Flask, status: int) -> None:
	response = app.test_client().get(f"/status/{status}", headers={"Accept-Encoding": "gzip"})
	assert response.status_code == status
	assert "Content-Encoding" not in response.headers
	assert "X-Flask-Squeeze-Minify" not in response.headers


def test_head_has_no_body(app: Flask) -> None:
	response = app.test_client().head("/static/sample.css", headers={"Accept-Encoding": "gzip"})
	assert response.data == b""


def test_size_threshold_is_inclusive(app: Flask) -> None:
	app.config["SQUEEZE_MIN_SIZE"] = len(CSS)
	response = app.test_client().get("/dynamic.css", headers={"Accept-Encoding": "gzip"})
	assert decoded_body(response) == b".box{color:red;margin:0}"
	assert response.headers["Content-Encoding"] == "gzip"

	app.config["SQUEEZE_MIN_SIZE"] = len(CSS) + 1
	response = app.test_client().get("/dynamic.css", headers={"Accept-Encoding": "gzip"})
	assert response.data == CSS
	assert "Content-Encoding" not in response.headers


def test_identity_response_varies_on_encoding(app: Flask) -> None:
	app.config["SQUEEZE_MINIFY_CSS"] = False
	response = app.test_client().get("/dynamic.css")
	assert response.data == CSS
	assert "Accept-Encoding" in response.headers["Vary"]


def test_static_cache_updates_after_file_change(app: Flask, tmp_path: Path) -> None:
	client = app.test_client()
	headers = {"Accept-Encoding": "gzip"}
	first = client.get("/static/sample.css", headers=headers)
	assert first.headers["X-Flask-Squeeze-Cache"] == "MISS"
	assert decoded_body(first) == b".box{color:red;margin:0}"
	assert client.get("/static/sample.css", headers=headers).headers["X-Flask-Squeeze-Cache"] == "HIT"
	cache_hit = client.get("/static/sample.css", headers=headers)
	assert cache_hit.headers["Content-Encoding"] == "gzip"
	assert decoded_body(cache_hit) == b".box{color:red;margin:0}"

	updated = b".box { color: blue; }"
	(tmp_path / "sample.css").write_bytes(updated)
	changed = client.get("/static/sample.css", headers=headers)
	assert changed.headers["X-Flask-Squeeze-Cache"] == "MISS"
	assert decoded_body(changed) == b".box{color:blue}"

	app.config["SQUEEZE_MINIFY_CSS"] = False
	unminified = client.get("/static/sample.css", headers=headers)
	assert unminified.headers["X-Flask-Squeeze-Cache"] == "MISS"
	assert decoded_body(unminified) == updated


def test_disk_cache_rejects_corrupt_data(tmp_path: Path) -> None:
	cache_dir = tmp_path / "cache"
	first_app = make_app(tmp_path, cache_dir)
	first = first_app.test_client().get("/static/sample.css", headers={"Accept-Encoding": "gzip"})
	assert first.headers["X-Flask-Squeeze-Cache"] == "MISS"
	cache_file = next(cache_dir.glob("*.cache"))
	cache_file.write_bytes(b"corrupted")

	restarted = make_app(tmp_path, cache_dir)
	response = restarted.test_client().get("/static/sample.css", headers={"Accept-Encoding": "gzip"})
	assert response.headers["X-Flask-Squeeze-Cache"] == "MISS"
	assert decoded_body(response) == b".box{color:red;margin:0}"


def test_distinct_paths_keep_distinct_cache_entries(app: Flask, tmp_path: Path) -> None:
	(tmp_path / "a_b.css").write_bytes(b".one { color: red; }")
	(tmp_path / "a").mkdir()
	(tmp_path / "a" / "b.css").write_bytes(b".two { color: blue; }")
	client = app.test_client()
	headers = {"Accept-Encoding": "gzip"}
	first = client.get("/static/a_b.css", headers=headers)
	second = client.get("/static/a/b.css", headers=headers)
	repeated = client.get("/static/a_b.css", headers=headers)
	assert first.headers["X-Flask-Squeeze-Cache"] == "MISS"
	assert second.headers["X-Flask-Squeeze-Cache"] == "MISS"
	assert repeated.headers["X-Flask-Squeeze-Cache"] == "HIT"
	assert decoded_body(repeated) == b".one{color:red}"


def test_concurrent_static_requests_preserve_content(tmp_path: Path) -> None:
	cache_dir = tmp_path / "cache"
	app = make_app(tmp_path, cache_dir)

	def fetch(_index: int) -> bytes:
		response = app.test_client().get("/static/sample.css", headers={"Accept-Encoding": "gzip"})
		return decoded_body(response)

	with ThreadPoolExecutor(max_workers=8) as executor:
		assert list(executor.map(fetch, range(16))) == [b".box{color:red;margin:0}"] * 16

	restarted = make_app(tmp_path, cache_dir)
	response = restarted.test_client().get("/static/sample.css", headers={"Accept-Encoding": "gzip"})
	assert decoded_body(response) == b".box{color:red;margin:0}"
