import pytest
from flask.testing import FlaskClient
from test_app import create_app
from werkzeug.wrappers import Response

########################################################################################
# Fixtures
##########


@pytest.fixture
def client():  # noqa
	app = create_app()
	app.testing = True
	with app.test_client() as test_client:
		yield test_client


@pytest.fixture(params=["", "gzip", "br", "deflate"])
def use_encoding(request):
	return request.param


@pytest.fixture(params=[False, True])
def use_minify_js(request):
	return request.param


@pytest.fixture(params=[False, True])
def use_minify_css(request):
	return request.param


########################################################################################
# Utilities
###########


def almost_equal(a, b, percent=0.01):
	diff = abs(int(a) - int(b))
	return diff < percent * int(a) and diff < percent * int(b)


def content_length_correct(r: Response) -> bool:
	return int(r.headers.get("Content-Length", 0)) == len(r.data)


########################################################################################
# Tests
########


def test_get_index(client: FlaskClient, use_encoding: str):
	print("test_get_index")
	r = client.get("/", headers={"Accept-Encoding": use_encoding})
	assert content_length_correct(r)
	length = r.headers.get("Content-Length")
	encoding = r.headers.get("Content-Encoding", "")

	assert use_encoding == encoding

	sizes = {
		"": 3_932_146,
		"br": 8_164,
		"deflate": 83_554,
		"gzip": 83_566,
	}

	assert almost_equal(length, sizes[use_encoding])


def test_get_css_file(client: FlaskClient, use_encoding: str, use_minify_css: bool):
	print("test_get_css_file with", use_encoding, "minify:", use_minify_css)
	client.application.config.update({"SQUEEZE_MINIFY_CSS": use_minify_css})
	r = client.get("/static/fomantic.css", headers={"Accept-Encoding": use_encoding})
	assert content_length_correct(r)
	response_length = r.headers.get("Content-Length")
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


def test_get_js_file(client: FlaskClient, use_encoding: str, use_minify_js: bool):
	print("test_get_js_file with", use_encoding, "minify:", use_minify_js)
	client.application.config.update({"SQUEEZE_MINIFY_JS": use_minify_js})
	r = client.get("/static/jquery.js", headers={"Accept-Encoding": use_encoding})
	assert content_length_correct(r)
	assert use_encoding == r.headers.get("Content-Encoding", "")


def test_get_jquery_no_minify(client: FlaskClient):
	client.application.config.update({"SQUEEZE_MINIFY_JS": False})
	r_orig = client.get("/static/jquery.js", headers={})
	assert content_length_correct(r_orig)
	assert "Content-Encoding" not in r_orig.headers
	assert r_orig.headers["Content-Length"] == "292458"
	assert "X-Uncompressed-Content-Length" not in r_orig.headers


def test_get_from_cache(client: FlaskClient, use_encoding: str):
	client.application.config.update({"SQUEEZE_MINIFY_JS": False})
	r = client.get("/static/jquery.min.js", headers={"Accept-Encoding": use_encoding})
	r_2 = client.get("/static/jquery.min.js", headers={"Accept-Encoding": use_encoding})
	assert r.data == r_2.data


def test_get_unknown_url(client: FlaskClient):
	r = client.get("/static/unknown.js", headers={"Accept-Encoding": "gzip"})
	assert r.status_code == 404


def test_get_same_repeatedly(client: FlaskClient):
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
	return "X-Breach-Exploit-Protection-Padding" in r.headers


def response_has_vary_header(r: Response) -> bool:
	return "Vary" in r.headers and "Accept-Encoding" in r.headers["Vary"]


########################################################################################
# Additional Tests
########################################################################################


def test_disable_compression(client: FlaskClient):
	"""Test that compression can be disabled."""
	client.application.config.update({"SQUEEZE_COMPRESS": False})
	r = client.get("/static/jquery.js", headers={"Accept-Encoding": "gzip"})
	assert "Content-Encoding" not in r.headers
	assert not response_has_breach_header(r)


def test_disable_minification(client: FlaskClient):
	"""Test that minification can be disabled."""
	client.application.config.update(
		{"SQUEEZE_MINIFY_JS": False, "SQUEEZE_MINIFY_CSS": False, "SQUEEZE_MINIFY_HTML": False}
	)
	r = client.get("/static/jquery.js", headers={"Accept-Encoding": "gzip"})
	assert "X-Flask-Squeeze-Minify-Duration" not in r.headers


def test_html_response_minification(client: FlaskClient):
	"""Test minification of HTML responses."""
	client.application.config.update({"SQUEEZE_MINIFY_HTML": True})
	r = client.get("/", headers={"Accept-Encoding": "gzip"})
	assert "X-Flask-Squeeze-Minify-Duration" in r.headers


def test_breach_header_presence(client: FlaskClient):
	"""Test the presence of the breach exploit protection header."""
	r = client.get("/", headers={"Accept-Encoding": "br"})
	assert response_has_breach_header(r)


def test_vary_header_presence(client: FlaskClient):
	"""Test the presence of the Vary header after compression."""
	r = client.get("/static/jquery.js", headers={"Accept-Encoding": "gzip"})
	assert response_has_vary_header(r)


def test_minification_and_compression_together(client: FlaskClient):
	"""Test both minification and compression are applied together."""
	client.application.config.update({"SQUEEZE_MINIFY_CSS": True})
	r = client.get("/static/fomantic.css", headers={"Accept-Encoding": "gzip"})
	assert "Content-Encoding" in r.headers
	assert "X-Flask-Squeeze-Minify-Duration" in r.headers
	assert content_length_correct(r)


def test_debug_headers_presence(client: FlaskClient):
	"""Test if debug headers are added when enabled."""
	client.application.config.update({"SQUEEZE_ADD_DEBUG_HEADERS": True})
	r = client.get("/static/fomantic.css", headers={"Accept-Encoding": "gzip"})
	assert "X-Flask-Squeeze-Total-Duration" in r.headers
	assert "X-Flask-Squeeze-Compress-Duration" in r.headers or "X-Flask-Squeeze-Minify-Duration" in r.headers
