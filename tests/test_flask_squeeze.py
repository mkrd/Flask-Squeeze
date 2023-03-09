import pytest
from test_app import create_app
from flask.testing import FlaskClient


@pytest.fixture
def client():
    app = create_app({'TESTING': True})
    app.config.update({"COMPRESS_LEVEL_DYNAMIC": 1})
    with app.test_client() as test_client:
        yield test_client


def test_get_accept_no_encoding(client: FlaskClient):
    print("Accept-Encoding: identity:")
    r = client.get('/', headers={})
    assert "Content-Encoding" not in r.headers
    assert r.headers["Content-Length"] == "3955741"


def test_get_gzip(client: FlaskClient):
    print("Using gzip:")
    r = client.get('/', headers={'Accept-Encoding': 'gzip'})
    assert r.headers["Content-Encoding"] == "gzip"
    assert r.headers["X-Uncompressed-Content-Length"] == "3955741"


def test_get_brotli(client: FlaskClient):
    print("Using brotli:")
    r = client.get('/', headers={'Accept-Encoding': 'br'})
    assert r.headers["Content-Encoding"] == "br"
    assert r.headers["X-Uncompressed-Content-Length"] == "3955741"


def test_get_deflate(client: FlaskClient):
    print("Using deflate:")
    r = client.get('/', headers={'Accept-Encoding': 'deflate'})
    assert r.headers["Content-Encoding"] == "deflate"
    assert r.headers["X-Uncompressed-Content-Length"] == "3955741"



def test_get_brotli_and_gzip(client: FlaskClient):
    print("Using brotli and gzip:")
    r = client.get('/', headers={'Accept-Encoding': 'br; gzip'})
    assert r.headers["Content-Encoding"] == "br"
    assert r.headers["X-Uncompressed-Content-Length"] == "3955741"





def test_get_brotli_css_file(client: FlaskClient):
    print("Using brotli to get css file:")
    r = client.get('/static/main.css', headers={'Accept-Encoding': 'br;'})
    assert r.headers["Content-Encoding"] == "br"


def test_get_brotli_js_file(client: FlaskClient):
    print("Using brotli to get css file:")
    r = client.get('/static/main.js', headers={'Accept-Encoding': 'br;'})
    assert r.headers["Content-Encoding"] == "br"
    print(r.headers["X-Uncompressed-Content-Length"])
    print(r.headers["Content-Length"])



def test_get_gzip_css_file(client: FlaskClient):
    print("Using gzip to get css file:")
    r = client.get('/static/main.css', headers={'Accept-Encoding': 'gzip;'})
    assert r.headers["Content-Encoding"] == "gzip"



def test_get_gzip_js_file(client: FlaskClient):
    print("Using gzip to get css file:")
    r = client.get('/static/main.js', headers={'Accept-Encoding': 'gzip;'})
    assert r.headers["Content-Encoding"] == "gzip"
    print(r.headers["X-Uncompressed-Content-Length"])
    print(r.headers["Content-Length"])


def test_get_jquery_no_minify(client: FlaskClient):
    client.application.config.update({"COMPRESS_MINIFY_JS": False})
    r_orig = client.get('/static/jquery.js', headers={})
    assert "Content-Encoding" not in r_orig.headers
    assert r_orig.headers["Content-Length"] == "292458"
    assert "X-Uncompressed-Content-Length" not in r_orig.headers


def test_get_jquery_with_minify(client: FlaskClient):
    print("test_get_jquery_with_minify")
    client.application.config.update({"COMPRESS_MINIFY_JS": True})
    r_orig = client.get('/static/jquery.js', headers={})
    assert "Content-Encoding" not in r_orig.headers
    print(r_orig.headers["Content-Length"])
    assert r_orig.headers["Content-Length"] == "144649"
    assert r_orig.headers["X-Uncompressed-Content-Length"] == "292458"
