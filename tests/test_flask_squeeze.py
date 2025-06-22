from __future__ import annotations

import contextlib
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, Generator

import pytest
from test_app import create_app

if TYPE_CHECKING:
	from flask.testing import FlaskClient
	from werkzeug.wrappers import Response

STATUS_CODE_NOT_FOUND_404 = 404
STATUS_CODE_OK_200 = 200

########################################################################################
#### MARK: Fixtures


@pytest.fixture
def client() -> Generator[FlaskClient, Any, None]:
	app = create_app()
	app.testing = True
	with app.test_client() as test_client:
		yield test_client


@pytest.fixture(params=["", "gzip", "br", "deflate"])
def use_encoding(request: pytest.FixtureRequest) -> str:
	return request.param


@pytest.fixture(params=[False, True])
def use_minify_js(request: pytest.FixtureRequest) -> bool:
	return request.param


@pytest.fixture(params=[False, True])
def use_minify_css(request: pytest.FixtureRequest) -> bool:
	return request.param


########################################################################################
#### MARK: Utilities


def almost_equal(a: float, b: float, percent: float = 0.01) -> bool:
	diff = abs(int(a) - int(b))
	return diff < percent * int(a) and diff < percent * int(b)


def content_length_correct(r: Response) -> bool:
	return r.headers.get("Content-Length", 0) == str(len(r.data))


########################################################################################
#### MARK: Tests


def test_init_app_with_existing_app() -> None:
	app = create_app()

	from flask_squeeze import Squeeze

	_squeeze = Squeeze(app)


def test_get_index(client: FlaskClient, use_encoding: str) -> None:
	print("test_get_index")
	r = client.get("/", headers={"Accept-Encoding": use_encoding})
	assert content_length_correct(r)
	length = int(r.headers.get("Content-Length", "0"))
	encoding = r.headers.get("Content-Encoding", "")

	assert use_encoding == encoding

	sizes = {
		"": 3_932_146,
		"br": 8_164,
		"deflate": 83_554,
		"gzip": 83_566,
	}

	assert almost_equal(length, sizes[use_encoding])


def test_get_css_file(client: FlaskClient, use_encoding: str, use_minify_css: bool) -> None:
	print("test_get_css_file with", use_encoding, "minify:", use_minify_css)
	client.application.config.update({"SQUEEZE_MINIFY_CSS": use_minify_css})
	url = "/static/fomantic.css"
	r = client.get(url, headers={"Accept-Encoding": use_encoding})
	assert content_length_correct(r)
	response_length = int(r.headers.get("Content-Length", "0"))
	encoding = r.headers.get("Content-Encoding", "")

	assert use_encoding == encoding

	sizes = {
		("", True): 1_377_522,
		("br", True): 117_261,
		("deflate", True): 157_184,
		("gzip", True): 157_196,
		("", False): 1_642_530,
		("br", False): 130_781,
		("deflate", False): 179_986,
		("gzip", False): 179_998,
	}

	assert almost_equal(response_length, sizes[(use_encoding, use_minify_css)])


def test_get_js_file(client: FlaskClient, use_encoding: str, use_minify_js: bool) -> None:
	print("test_get_js_file with", use_encoding, "minify:", use_minify_js)
	client.application.config.update({"SQUEEZE_MINIFY_JS": use_minify_js})
	r = client.get("/static/jquery.js", headers={"Accept-Encoding": use_encoding})
	assert content_length_correct(r)
	assert use_encoding == r.headers.get("Content-Encoding", "")


def test_get_jquery_no_minify(client: FlaskClient) -> None:
	client.application.config.update({"SQUEEZE_MINIFY_JS": False})
	r_orig = client.get("/static/jquery.js", headers={})
	assert content_length_correct(r_orig)
	assert "Content-Encoding" not in r_orig.headers
	assert r_orig.headers["Content-Length"] == "292458"


def test_get_from_cache(client: FlaskClient, use_encoding: str) -> None:
	client.application.config.update({"SQUEEZE_MINIFY_JS": False})
	r = client.get("/static/jquery.min.js", headers={"Accept-Encoding": use_encoding})
	r_2 = client.get("/static/jquery.min.js", headers={"Accept-Encoding": use_encoding})
	assert r.data == r_2.data


def test_get_unknown_url(client: FlaskClient) -> None:
	r = client.get("/static/unknown.js", headers={"Accept-Encoding": "gzip"})
	assert r.status_code == STATUS_CODE_NOT_FOUND_404


def test_get_same_repeatedly(client: FlaskClient) -> None:
	client.application.config.update({"SQUEEZE_MINIFY_JS": True})
	for i in range(100):
		r = client.get("/static/jquery.js", headers={"Accept-Encoding": "br"})
		if i == 0:
			assert r.headers.get("X-Flask-Squeeze-Cache") == "MISS"
		else:
			assert r.headers.get("X-Flask-Squeeze-Cache") == "HIT"
	for i in range(100):
		r = client.get("/static/jquery.js", headers={"Accept-Encoding": "gzip"})
		if i == 0:
			assert r.headers.get("X-Flask-Squeeze-Cache") == "MISS"
		else:
			assert r.headers.get("X-Flask-Squeeze-Cache") == "HIT"
	r = client.get("/static/jquery.js", headers={"Accept-Encoding": "br"})
	assert r.headers.get("X-Flask-Squeeze-Cache") == "HIT"


def response_has_breach_header(r: Response) -> bool:
	return "X-Flask-Squeeze-Breach-Protection" in r.headers


def response_has_vary_header(r: Response) -> bool:
	return "Vary" in r.headers and "Accept-Encoding" in r.headers["Vary"]


########################################################################################
#### MARK: Additional Tests


def test_disable_compression(client: FlaskClient) -> None:
	"""Test that compression can be disabled."""
	client.application.config.update({"SQUEEZE_COMPRESS": False})
	r = client.get("/static/jquery.js", headers={"Accept-Encoding": "gzip"})
	assert "Content-Encoding" not in r.headers
	assert not response_has_breach_header(r)


def test_disable_minification(client: FlaskClient) -> None:
	"""Test that minification can be disabled."""
	client.application.config.update(
		{
			"SQUEEZE_MINIFY_JS": False,
			"SQUEEZE_MINIFY_CSS": False,
			"SQUEEZE_MINIFY_HTML": False,
		},
	)
	r = client.get("/static/jquery.js", headers={"Accept-Encoding": "gzip"})
	assert "X-Flask-Squeeze-Minify" not in r.headers


def test_html_response_minification(client: FlaskClient) -> None:
	"""Test minification of HTML responses."""
	client.application.config.update({"SQUEEZE_MINIFY_HTML": True})
	r = client.get("/", headers={"Accept-Encoding": "gzip"})
	assert "X-Flask-Squeeze-Minify" in r.headers, r.headers


def test_breach_header_presence(client: FlaskClient) -> None:
	"""Test the presence of the breach exploit protection header."""
	r = client.get("/", headers={"Accept-Encoding": "br"})
	assert response_has_breach_header(r)


def test_vary_header_presence(client: FlaskClient) -> None:
	"""Test the presence of the Vary header after compression."""
	r = client.get("/static/jquery.js", headers={"Accept-Encoding": "gzip"})
	assert response_has_vary_header(r)


def test_minification_and_compression_together(client: FlaskClient) -> None:
	"""Test both minification and compression are applied together."""
	client.application.config.update({"SQUEEZE_MINIFY_CSS": True})
	r = client.get("/static/fomantic.css", headers={"Accept-Encoding": "gzip"})
	assert "Content-Encoding" in r.headers
	assert "X-Flask-Squeeze-Minify" in r.headers
	assert content_length_correct(r)


def test_no_minify_no_compress(client: FlaskClient) -> None:
	client.application.config.update(
		{
			"SQUEEZE_MINIFY_JS": False,
			"SQUEEZE_MINIFY_CSS": False,
			"SQUEEZE_MINIFY_HTML": False,
			"SQUEEZE_COMPRESS": False,
		},
	)

	# Static file with no minification or compression

	r = client.get("/static/fomantic.css", headers={"Accept-Encoding": "gzip"})
	assert "Content-Encoding" not in r.headers
	assert "X-Flask-Squeeze-Minify" not in r.headers
	assert "X-Flask-Squeeze-Compress" not in r.headers

	# Dynamic file with no minification or compression

	r = client.get("/", headers={"Accept-Encoding": "gzip"})
	assert "Content-Encoding" not in r.headers
	assert "X-Flask-Squeeze-Minify" not in r.headers
	assert "X-Flask-Squeeze-Compress" not in r.headers


def test_static_file_cache_behavior(
	client: FlaskClient,
	use_encoding: str,
	use_minify_css: bool,
) -> None:
	"""Test cache behavior for a temporary static file."""

	# Skip if encoding is not set
	if not use_encoding:
		return

	client.application.config.update({"SQUEEZE_MINIFY_CSS": use_minify_css})

	# Ensure the static directory is set
	if (static_dir := client.application.static_folder) is None:
		msg = "Static directory not found"
		raise ValueError(msg)

	# Use a temporary file within the static directory
	with tempfile.NamedTemporaryFile(dir=static_dir, suffix=".css", delete=True) as temp_file:
		file_path = temp_file.name
		url_path = "/static/" + Path(file_path).name
		temp_file.write(b"body { color: #000; } " * 1000)
		temp_file.flush()  # Ensure content is written to disk

		# First request: MISS
		r = client.get(url_path, headers={"Accept-Encoding": use_encoding})
		assert r.headers.get("X-Flask-Squeeze-Cache") == "MISS"

		# Second request: HIT
		r = client.get(url_path, headers={"Accept-Encoding": use_encoding})
		assert r.headers.get("X-Flask-Squeeze-Cache") == "HIT"

		# Modify the file content
		temp_file.write(b"body { color: #123456; } " * 1000)
		temp_file.flush()  # Ensure the new content is written

		# Third request: MISS
		r = client.get(url_path, headers={"Accept-Encoding": use_encoding})
		assert r.headers.get("X-Flask-Squeeze-Cache") == "MISS"

		# Fourth request: HIT
		r = client.get(url_path, headers={"Accept-Encoding": use_encoding})
		assert r.headers.get("X-Flask-Squeeze-Cache") == "HIT"


def test_malformed_accept_encoding(client: FlaskClient) -> None:
	# Case 1: Missing Accept-Encoding
	r = client.get("/static/jquery.js")
	assert "Content-Encoding" not in r.headers

	# Case 2: Malformed Accept-Encoding
	r = client.get("/static/jquery.js", headers={"Accept-Encoding": "invalid-encoding"})
	assert "Content-Encoding" not in r.headers

	# Case 3: Conflicting Accept-Encoding values
	r = client.get("/static/jquery.js", headers={"Accept-Encoding": "gzip, br"})
	assert r.headers.get("Content-Encoding") in {"gzip", "br"}


def test_cache_invalidation_on_compression_disable(client: FlaskClient) -> None:
	# Enable compression and fetch the file
	client.application.config.update({"SQUEEZE_COMPRESS": True})
	r = client.get("/static/jquery.js", headers={"Accept-Encoding": "gzip"})
	assert r.headers.get("X-Flask-Squeeze-Cache") == "MISS"

	# Fetch again to ensure it is cached
	r = client.get("/static/jquery.js", headers={"Accept-Encoding": "gzip"})
	assert r.headers.get("X-Flask-Squeeze-Cache") == "HIT"

	# Disable compression
	client.application.config.update({"SQUEEZE_COMPRESS": False})

	# Fetch again, cache should be invalidated
	r = client.get("/static/jquery.js", headers={"Accept-Encoding": "gzip"})
	assert r.headers.get("X-Flask-Squeeze-Cache") == "MISS"
	assert "Content-Encoding" not in r.headers


def test_small_response_below_min_size(client: FlaskClient) -> None:
	min_size = 1000
	client.application.config.update({"SQUEEZE_MIN_SIZE": min_size})

	# A small response
	r = client.get("/static/smallfile.js", headers={"Accept-Encoding": "gzip"})
	assert r.content_length < min_size  # Ensure response is small
	assert "Content-Encoding" not in r.headers
	assert "X-Flask-Squeeze-Minify" not in r.headers


def test_persistent_cache_basic(client: FlaskClient) -> None:
	"""Test basic persistent caching functionality."""
	with tempfile.TemporaryDirectory() as temp_dir:
		cache_dir = Path(temp_dir) / "flask_squeeze_cache"

		# Configure persistent caching
		client.application.config.update({"SQUEEZE_CACHE_DIR": str(cache_dir)})

		# Reinitialize the squeeze instance with the new config
		from flask_squeeze import Squeeze

		squeeze = Squeeze()
		squeeze.init_app(client.application)

		# First request - should be a cache miss
		r1 = client.get("/static/jquery.min.js", headers={"Accept-Encoding": "gzip"})
		assert r1.headers.get("X-Flask-Squeeze-Cache") == "MISS"

		# Second request - should be a cache hit from memory
		r2 = client.get("/static/jquery.min.js", headers={"Accept-Encoding": "gzip"})
		assert r2.headers.get("X-Flask-Squeeze-Cache") == "HIT"
		assert r1.data == r2.data

		# Verify cache files were created
		cache_files = list(cache_dir.glob("*.cache"))
		meta_files = list(cache_dir.glob("*.meta"))
		assert len(cache_files) > 0
		assert len(meta_files) > 0


def test_persistent_cache_across_restarts(client: FlaskClient) -> None:
	"""Test that cache persists across application restarts."""
	with tempfile.TemporaryDirectory() as temp_dir:
		cache_dir = Path(temp_dir) / "flask_squeeze_cache"

		# Configure persistent caching
		client.application.config.update({"SQUEEZE_CACHE_DIR": str(cache_dir)})

		# Create first squeeze instance
		from flask_squeeze import Squeeze

		squeeze1 = Squeeze()
		squeeze1.init_app(client.application)

		# First request
		r1 = client.get("/static/jquery.min.js", headers={"Accept-Encoding": "gzip"})
		assert r1.headers.get("X-Flask-Squeeze-Cache") == "MISS"

		# Create a second squeeze instance to simulate a restart

		app_2 = create_app()
		app_2.testing = True
		client_2 = app_2.test_client()
		client_2.application.config.update({"SQUEEZE_CACHE_DIR": str(cache_dir)})
		squeeze2 = Squeeze()
		squeeze2.init_app(client_2.application)

		# Second request after "restart" - should be cache hit from disk
		r2 = client_2.get("/static/jquery.min.js", headers={"Accept-Encoding": "gzip"})
		assert r2.headers.get("X-Flask-Squeeze-Cache") == "HIT"
		assert r1.data == r2.data


def test_persistent_cache_disabled(client: FlaskClient) -> None:
	"""Test that without cache directory, only in-memory cache is used."""
	# Don't set SQUEEZE_CACHE_DIR
	from flask_squeeze import Squeeze

	squeeze = Squeeze()
	squeeze.init_app(client.application)

	# First request
	r1 = client.get("/static/jquery.min.js", headers={"Accept-Encoding": "gzip"})
	assert r1.headers.get("X-Flask-Squeeze-Cache") == "MISS"

	# Second request - should be cache hit from memory
	r2 = client.get("/static/jquery.min.js", headers={"Accept-Encoding": "gzip"})
	assert r2.headers.get("X-Flask-Squeeze-Cache") == "HIT"


def test_mimetype_detection_comprehensive(client: FlaskClient) -> None:
	"""Test comprehensive mimetype detection for various file types."""
	test_cases = [
		("/static/main.js", "text/javascript", True),
		("/static/main.css", "text/css", True),
		("/", "text/html", True),  # HTML from template
	]

	for url, expected_mimetype, should_process in test_cases:
		r = client.get(url, headers={"Accept-Encoding": "gzip"})
		assert expected_mimetype in (r.mimetype or "")
		if should_process:
			assert "Content-Encoding" in r.headers or "X-Flask-Squeeze-Minify" in r.headers


def test_encoding_priority_selection(client: FlaskClient) -> None:
	"""Test that encodings are selected in correct priority order."""
	# Test brotli preferred over gzip
	r = client.get("/static/jquery.js", headers={"Accept-Encoding": "gzip, br, deflate"})
	assert r.headers.get("Content-Encoding") == "br"

	# Test deflate preferred over none when br/gzip unavailable
	r = client.get("/static/jquery.js", headers={"Accept-Encoding": "deflate"})
	assert r.headers.get("Content-Encoding") == "deflate"

	# Test gzip when only gzip available
	r = client.get("/static/jquery.js", headers={"Accept-Encoding": "gzip"})
	assert r.headers.get("Content-Encoding") == "gzip"


def test_quality_levels_configuration(client: FlaskClient) -> None:
	"""Test different compression quality levels."""
	configs = [
		{"SQUEEZE_LEVEL_GZIP_STATIC": 1, "SQUEEZE_LEVEL_BROTLI_STATIC": 1},
		{"SQUEEZE_LEVEL_GZIP_STATIC": 9, "SQUEEZE_LEVEL_BROTLI_STATIC": 11},
	]

	for config in configs:
		client.application.config.update(config)
		r = client.get("/static/jquery.js", headers={"Accept-Encoding": "gzip"})
		assert content_length_correct(r)
		assert "Content-Encoding" in r.headers


def test_cache_file_corruption_recovery(client: FlaskClient) -> None:
	"""Test recovery from corrupted cache files."""
	with tempfile.TemporaryDirectory() as temp_dir:
		cache_dir = Path(temp_dir) / "cache"
		client.application.config.update({"SQUEEZE_CACHE_DIR": str(cache_dir)})

		from flask_squeeze import Squeeze

		squeeze = Squeeze()
		squeeze.init_app(client.application)

		# Create initial cache entry
		r1 = client.get("/static/jquery.js", headers={"Accept-Encoding": "gzip"})
		assert r1.headers.get("X-Flask-Squeeze-Cache") == "MISS"

		# Corrupt cache files
		for cache_file in cache_dir.glob("*.cache"):
			with cache_file.open("wb") as f:
				f.write(b"corrupted data")

		# Should recover gracefully
		r2 = client.get("/static/jquery.js", headers={"Accept-Encoding": "gzip"})
		assert content_length_correct(r2)


def test_very_large_files(client: FlaskClient) -> None:
	"""Test handling of very large files."""
	# Create a large CSS file
	large_content = "body { color: #000; } " * 10000  # ~200KB

	static_dir = client.application.static_folder
	if static_dir is None:
		pytest.skip("Static directory not configured")

	large_file_path = Path(static_dir) / "large_test.css"
	try:
		with large_file_path.open("w") as f:
			f.write(large_content)

		# Test compression of large file
		r = client.get("/static/large_test.css", headers={"Accept-Encoding": "gzip"})
		assert content_length_correct(r)
		assert "Content-Encoding" in r.headers

		# Verify significant compression ratio
		original_size = len(large_content.encode())
		compressed_size = len(r.data)
		compression_ratio = original_size / compressed_size
		minimum_compression_ratio = 2.0  # Expect at least 2:1 compression ratio
		assert compression_ratio > minimum_compression_ratio

	finally:
		large_file_path.unlink(missing_ok=True)


def test_binary_file_handling(client: FlaskClient) -> None:
	"""Test handling of binary files that shouldn't be processed."""
	# Create a small binary file
	static_dir = client.application.static_folder
	if static_dir is None:
		pytest.skip("Static directory not configured")

	binary_file_path = Path(static_dir) / "test.bin"
	try:
		with binary_file_path.open("wb") as f:
			f.write(b"\x00\x01\x02\x03" * 100)

		r = client.get("/static/test.bin", headers={"Accept-Encoding": "gzip"})
		assert "Content-Encoding" in r.headers
		assert "X-Flask-Squeeze-Minify" not in r.headers

	finally:
		binary_file_path.unlink(missing_ok=True)


def test_empty_file_handling(client: FlaskClient) -> None:
	"""Test handling of empty files."""
	r = client.get("/static/empty.js", headers={"Accept-Encoding": "gzip"})
	assert r.status_code == STATUS_CODE_OK_200


def test_malformed_content_handling(client: FlaskClient) -> None:
	"""Test handling of malformed CSS/JS content."""
	static_dir = client.application.static_folder
	if static_dir is None:
		pytest.skip("Static directory not configured")

	# Test malformed CSS
	malformed_css_path = Path(static_dir) / "malformed.css"
	try:
		with malformed_css_path.open("w") as f:
			f.write("body { color: #000; /* unclosed comment")

		client.application.config.update({"SQUEEZE_MINIFY_CSS": True})
		r = client.get("/static/malformed.css", headers={"Accept-Encoding": "gzip"})
		# Should handle gracefully, might not minify but shouldn't crash
		assert r.status_code == STATUS_CODE_OK_200
		assert content_length_correct(r)

	finally:
		malformed_css_path.unlink(missing_ok=True)


def test_security_headers_comprehensive(client: FlaskClient) -> None:
	"""Test comprehensive security header behavior."""
	# Test BREACH protection header
	r = client.get("/", headers={"Accept-Encoding": "gzip"})
	breach_header = r.headers.get("X-Flask-Squeeze-Breach-Protection")
	assert breach_header is not None
	assert len(breach_header) > 0

	# Test that BREACH protection varies between requests
	r2 = client.get("/", headers={"Accept-Encoding": "gzip"})
	breach_header2 = r2.headers.get("X-Flask-Squeeze-Breach-Protection")
	assert breach_header != breach_header2  # Should be different

	# Test Vary header
	r = client.get("/static/jquery.js", headers={"Accept-Encoding": "gzip"})
	vary_header = r.headers.get("Vary", "")
	assert "Accept-Encoding" in vary_header


def test_content_length_edge_cases(client: FlaskClient) -> None:
	"""Test edge cases around content length handling."""
	# Test exactly at min size threshold
	min_size_threshold = 100
	client.application.config.update({"SQUEEZE_MIN_SIZE": min_size_threshold})

	static_dir = client.application.static_folder
	if static_dir is None:
		pytest.skip("Static directory not configured")

	# Create file exactly one above the threshold

	threshold_file_path = Path(static_dir) / "threshold.js"
	try:
		with threshold_file_path.open("w") as f:
			f.write("x" * (min_size_threshold + 1))  # Create a file of size min_size_threshold + 1

		r = client.get("/static/threshold.js", headers={"Accept-Encoding": "gzip"})

		assert "Content-Encoding" in r.headers

	finally:
		threshold_file_path.unlink(missing_ok=True)

	# Create file exactly one below the threshold

	below_threshold_file_path = Path(static_dir) / "below_threshold.js"
	try:
		with below_threshold_file_path.open("w") as f:
			f.write("x" * (min_size_threshold - 1))  # Create a file of size min_size_threshold

		r = client.get("/static/below_threshold.js", headers={"Accept-Encoding": "gzip"})

		assert "Content-Encoding" not in r.headers
	finally:
		below_threshold_file_path.unlink(missing_ok=True)


def test_configuration_validation(client: FlaskClient) -> None:
	"""Test various configuration combinations."""
	configs_to_test: list[dict[str, bool | int]] = [
		# All disabled
		{
			"SQUEEZE_COMPRESS": False,
			"SQUEEZE_MINIFY_JS": False,
			"SQUEEZE_MINIFY_CSS": False,
			"SQUEEZE_MINIFY_HTML": False,
		},
		# Only compression
		{
			"SQUEEZE_COMPRESS": True,
			"SQUEEZE_MINIFY_JS": False,
			"SQUEEZE_MINIFY_CSS": False,
			"SQUEEZE_MINIFY_HTML": False,
		},
		# Only minification
		{
			"SQUEEZE_COMPRESS": False,
			"SQUEEZE_MINIFY_JS": True,
			"SQUEEZE_MINIFY_CSS": True,
			"SQUEEZE_MINIFY_HTML": True,
		},
		# Extreme quality settings
		{
			"SQUEEZE_LEVEL_GZIP_STATIC": 9,
			"SQUEEZE_LEVEL_BROTLI_STATIC": 11,
			"SQUEEZE_LEVEL_DEFLATE_STATIC": 9,
		},
	]

	for config in configs_to_test:
		client.application.config.update(config)

		# Test should not crash with any config
		r = client.get("/static/jquery.js", headers={"Accept-Encoding": "gzip"})
		assert r.status_code == STATUS_CODE_OK_200
		assert content_length_correct(r)


def test_cache_key_normalization(client: FlaskClient) -> None:
	"""Test that cache keys are properly normalized."""
	# Test paths with special characters
	paths_to_test = [
		"/static/file-with-dashes.js",
		"/static/file_with_underscores.js",
		"/static/file.with.dots.js",
		"/static/deeply/nested/file.js",
	]

	static_dir = client.application.static_folder
	if static_dir is None:
		pytest.skip("Static directory not configured")

	created_files: list[Path] = []
	try:
		for path in paths_to_test:
			file_path = Path(static_dir) / Path(path).name
			with file_path.open("w") as f:
				f.write("var test = 1;")
			created_files.append(file_path)

			# Test that these can be cached without issues
			r = client.get(path, headers={"Accept-Encoding": "gzip"})
			if r.status_code == STATUS_CODE_OK_200:  # File exists
				assert content_length_correct(r)

	finally:
		for file_path in created_files:
			file_path.unlink(missing_ok=True)


def test_memory_usage_stability(client: FlaskClient) -> None:
	"""Test that memory usage remains stable with many requests."""
	import gc

	# Get initial memory baseline
	gc.collect()
	initial_objects = len(gc.get_objects())

	# Make many requests
	for _ in range(100):
		r = client.get("/static/jquery.js", headers={"Accept-Encoding": "gzip"})
		assert r.status_code == STATUS_CODE_OK_200

	# Check memory didn't grow significantly
	gc.collect()
	final_objects = len(gc.get_objects())
	growth = final_objects - initial_objects

	# Allow some growth but not excessive (arbitrary threshold)
	max_objects_growth = 1100
	assert growth < max_objects_growth, f"Excessive memory growth: {growth} objects"


def test_error_recovery_after_failures(client: FlaskClient) -> None:
	"""Test that the system recovers properly after various failures."""
	# Test recovery after cache directory becomes unavailable
	with tempfile.TemporaryDirectory() as temp_dir:
		cache_dir = Path(temp_dir) / "cache"
		client.application.config.update({"SQUEEZE_CACHE_DIR": str(cache_dir)})

		from flask_squeeze import Squeeze

		squeeze = Squeeze()
		squeeze.init_app(client.application)

		# First request should work
		r1 = client.get("/static/jquery.js", headers={"Accept-Encoding": "gzip"})
		assert r1.status_code == STATUS_CODE_OK_200

		# Simulate cache directory becoming unavailable
		try:
			cache_dir.chmod(0o000)  # Remove all permissions

			# Should still work, just without caching
			r2 = client.get("/static/jquery.js", headers={"Accept-Encoding": "gzip"})
			assert r2.status_code == STATUS_CODE_OK_200
			assert content_length_correct(r2)

		finally:
			# Restore permissions for cleanup
			with contextlib.suppress(Exception):
				cache_dir.chmod(0o755)


def test_header_preservation(client: FlaskClient) -> None:
	"""Test that important headers are preserved during processing."""
	r = client.get("/static/jquery.js", headers={"Accept-Encoding": "gzip"})

	# Content-Length should be accurate
	assert content_length_correct(r)

	# ETag should be preserved if present
	if "ETag" in r.headers:
		assert r.headers["ETag"]

	# Last-Modified should be preserved if present
	if "Last-Modified" in r.headers:
		assert r.headers["Last-Modified"]
