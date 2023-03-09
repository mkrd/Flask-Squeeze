import pytest
from test_app import create_app
from flask.testing import FlaskClient


@pytest.fixture
def client():
	app = create_app({"TESTING": True})
	app.config.update({"COMPRESS_LEVEL_DYNAMIC": 1})
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




def almost_equal(a, b, percent=0.01):
	diff = abs(int(a) - int(b))
	return diff < percent * int(a) and diff < percent * int(b)



def test_get_index(client: FlaskClient, use_encoding: str):
	print("test_get_index")
	r = client.get("/", headers={"Accept-Encoding": use_encoding})
	length = r.headers.get("Content-Length")
	encoding = r.headers.get("Content-Encoding", "")

	assert use_encoding == encoding
	if use_encoding == "":
		assert "X-Uncompressed-Content-Length" not in r.headers
	else:
		assert r.headers["X-Uncompressed-Content-Length"] == "3955741"

	sizes = {
		"": 3_955_741,
		"br": 7_183,
		"deflate": 83_466,
		"gzip": 83_477,
	}

	assert almost_equal(length, sizes[use_encoding])



def test_get_css_file(client: FlaskClient, use_encoding: str, use_minify_css: bool):
	print("test_get_css_file with", use_encoding, "minify:", use_minify_css)
	client.application.config.update({"COMPRESS_MINIFY_CSS": use_minify_css})
	r = client.get("/static/fomantic.css", headers={"Accept-Encoding": use_encoding})
	length = r.headers.get("Content-Length")
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

	assert almost_equal(length, sizes[(use_encoding, use_minify_css)])



def test_get_js_file(client: FlaskClient, use_encoding: str, use_minify_js: bool):
	print("test_get_js_file with", use_encoding, "minify:", use_minify_js)
	client.application.config.update({"COMPRESS_MINIFY_JS": use_minify_js})
	r = client.get("/static/jquery.js", headers={"Accept-Encoding": use_encoding})
	encoding = r.headers.get("Content-Encoding", "")
	assert encoding == use_encoding



def test_get_jquery_no_minify(client: FlaskClient):
	client.application.config.update({"COMPRESS_MINIFY_JS": False})
	r_orig = client.get("/static/jquery.js", headers={})
	assert "Content-Encoding" not in r_orig.headers
	assert r_orig.headers["Content-Length"] == "292458"
	assert "X-Uncompressed-Content-Length" not in r_orig.headers


def test_get_from_cache(client: FlaskClient, use_encoding: str):
	client.application.config.update({"COMPRESS_MINIFY_JS": False})
	r   = client.get("/static/jquery.min.js", headers={"Accept-Encoding": use_encoding})
	r_2 = client.get("/static/jquery.min.js", headers={"Accept-Encoding": use_encoding})
	assert r.data == r_2.data


def test_get_unknown_url(client: FlaskClient):
	r = client.get("/static/unknown.js", headers={"Accept-Encoding": "gzip"})
	assert r.status_code == 404



def test_get_jquery_with_minify(client: FlaskClient):
	print("test_get_jquery_with_minify")
	client.application.config.update({"COMPRESS_MINIFY_JS": True})
	r_orig = client.get("/static/jquery.js", headers={})
	assert "Content-Encoding" not in r_orig.headers
	print(r_orig.headers["Content-Length"])
	assert r_orig.headers["Content-Length"] == "144649"
	assert r_orig.headers["X-Uncompressed-Content-Length"] == "292458"
