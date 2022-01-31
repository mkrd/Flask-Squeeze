import pytest
from test_app import create_app
from flask.testing import FlaskClient



@pytest.fixture
def client():
    app = create_app({'TESTING': True})
    with app.test_client() as test_client:
        yield test_client



def test_get_gzip(client: FlaskClient):
    r = client.get('/', headers={'Accept-Encoding': 'gzip'})
    assert r.headers["Content-Encoding"] == "gzip"
    assert r.headers["X-Uncompressed-Content-Length"] == "3955741"

def test_get_brotli(client: FlaskClient):
    r = client.get('/', headers={'Accept-Encoding': 'br'})
    assert r.headers["Content-Encoding"] == "br"
    assert r.headers["X-Uncompressed-Content-Length"] == "3955741"

def test_get_brotli_and_gzip(client: FlaskClient):
    r = client.get('/', headers={'Accept-Encoding': 'br; gzip'})
    assert r.headers["Content-Encoding"] == "br"
    assert r.headers["X-Uncompressed-Content-Length"] == "3955741"

def test_get_accept_no_encoding(client: FlaskClient):
    r = client.get('/', headers={})
    assert "Content-Encoding" not in r.headers
    assert r.headers["Content-Length"] == "3955741"
