import unittest
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, Response
from playwright.sync_api import Route, expect, sync_playwright

from flask_squeeze import Squeeze
from tests.buffered_client import BufferedTestClient


class BrowserHtmxTest(unittest.TestCase):
	def test_htmx_request_and_swap_in_browser(self) -> None:
		app = Flask(__name__, static_folder=str(Path(__file__).parent / "fixtures"), static_url_path="/static")
		app.config.update(SQUEEZE_MIN_SIZE=0)

		@app.get("/")
		def index() -> Response:
			return Response(
				'<script src="/static/htmx.js"></script>'
				'<button hx-get="/fragment" hx-target="#result">Load</button>'
				'<div id="result"></div>'
				'<button hx-get="/row" hx-target="#rows" hx-swap="beforeend">Add row</button>'
				'<table><tbody id="rows"></tbody></table>',
				mimetype="text/html",
			)

		@app.get("/fragment")
		def fragment() -> Response:
			return Response("<span>Loaded</span>", mimetype="text/html")

		@app.get("/row")
		def row() -> Response:
			return Response("<tr><td>First</td><td>Second</td></tr>", mimetype="text/html")

		Squeeze(app)
		app.test_client_class = BufferedTestClient
		client = app.test_client()
		paths: list[str] = []

		def serve(route: Route) -> None:
			path = urlsplit(route.request.url).path
			paths.append(path)
			response = client.get(path)
			route.fulfill(status=response.status_code, body=response.data, content_type=response.content_type)

		playwright = self.enterContext(sync_playwright())
		browser = playwright.chromium.launch()
		self.addCleanup(browser.close)
		page = browser.new_page()
		page.route("**/*", serve)
		page.goto("http://squeeze.test/")
		self.assertEqual(page.evaluate("typeof htmx"), "object")
		page.get_by_role("button", name="Load").click()
		expect(page.locator("#result")).to_have_text("Loaded")
		self.assertIn("/fragment", paths)
		page.get_by_role("button", name="Add row").click()
		expect(page.locator("#rows > tr > td")).to_have_text(["First", "Second"])
