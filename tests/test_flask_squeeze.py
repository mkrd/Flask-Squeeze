import pytest
from test_app import create_app
from flask.testing import FlaskClient


@pytest.fixture
def client():
    app = create_app({'TESTING': True})
    app.config.update({"COMPRESS_LEVEL_DYNAMIC": 1})
    with app.test_client() as test_client:
        yield test_client


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


def test_get_brotli_and_gzip(client: FlaskClient):
    print("Using brotli and gzip:")
    r = client.get('/', headers={'Accept-Encoding': 'br; gzip'})
    assert r.headers["Content-Encoding"] == "br"
    assert r.headers["X-Uncompressed-Content-Length"] == "3955741"


def test_get_accept_no_encoding(client: FlaskClient):
    print("Accept-Encoding: identity:")
    r = client.get('/', headers={})
    assert "Content-Encoding" not in r.headers
    assert r.headers["Content-Length"] == "3955741"


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
