import unittest
from functools import partial
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit

from flask import Flask, Response
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server

from flask_squeeze import Squeeze
from flask_squeeze.plan import Encoding

MINIFICATION_SCRIPT = """
// browser-minification-marker
document.getElementById("script-action").addEventListener("click", function () {
	document.getElementById("script-result").textContent = "Minified script executed";
});
"""


class BrowserHtmxTest(unittest.TestCase):
	def test_htmx_request_and_swap_in_browser(self) -> None:
		app = Flask(__name__, static_folder=str(Path(__file__).parent / "fixtures"), static_url_path="/static")
		app.config.update(SQUEEZE_MIN_SIZE=0)

		@app.get("/")
		def index() -> Response:
			return Response(
				'<script src="/static/htmx.js"></script>'
				'<script src="/minified.js" defer></script>'
				'<button id="script-action">Run script</button><div id="script-result"></div>'
				'<button hx-get="/fragment" hx-target="#result">Load</button>'
				'<div id="result"></div>'
				'<button hx-get="/row" hx-target="#rows" hx-swap="beforeend">Add row</button>'
				'<table><tbody id="rows"></tbody></table>',
				mimetype="text/html",
			)

		@app.get("/minified.js")
		def minified_js() -> Response:
			return Response(MINIFICATION_SCRIPT, mimetype="text/javascript")

		@app.get("/fragment")
		def fragment() -> Response:
			return Response("<span>Loaded</span>", mimetype="text/html")

		@app.get("/row")
		def row() -> Response:
			return Response("<tr><td>First</td><td>Second</td></tr>", mimetype="text/html")

		Squeeze(app)
		server = self.enterContext(make_server("127.0.0.1", 0, app))
		server_thread = Thread(target=partial(server.serve_forever, poll_interval=0.05), daemon=True)
		server_thread.start()

		def stop_server() -> None:
			server.shutdown()
			server_thread.join(timeout=5)
			self.assertFalse(server_thread.is_alive(), "HTTP server failed to stop")

		self.addCleanup(stop_server)

		playwright = self.enterContext(sync_playwright())
		browser = playwright.chromium.launch()
		self.addCleanup(browser.close)
		page = browser.new_page()
		with (
			page.expect_response(lambda response: urlsplit(response.url).path == "/static/htmx.js") as script,
			page.expect_response(lambda response: urlsplit(response.url).path == "/minified.js") as minified_script,
		):
			initial = page.goto(f"http://127.0.0.1:{server.server_port}/")
		if initial is None:
			self.fail("Navigation did not return a response")
		encodings = {encoding.value for encoding in Encoding}
		self.assertEqual(initial.status, 200)
		self.assertIn(initial.headers["content-encoding"], encodings)
		self.assertEqual(script.value.status, 200)
		self.assertIn(script.value.headers["content-encoding"], encodings)
		self.assertEqual(page.evaluate("typeof htmx"), "object")
		self.assertEqual(minified_script.value.status, 200)
		self.assertIn(minified_script.value.headers["content-encoding"], encodings)
		minified_body = minified_script.value.body()
		self.assertLess(len(minified_body), len(MINIFICATION_SCRIPT.encode("utf-8")))
		self.assertNotIn(b"browser-minification-marker", minified_body)
		page.get_by_role("button", name="Run script").click()
		expect(page.locator("#script-result")).to_have_text("Minified script executed")
		with page.expect_response(lambda response: urlsplit(response.url).path == "/fragment") as fragment_response:
			page.get_by_role("button", name="Load").click()
		expect(page.locator("#result")).to_have_text("Loaded")
		self.assertEqual(fragment_response.value.status, 200)
		self.assertNotIn("content-encoding", fragment_response.value.headers)
		self.assertEqual(fragment_response.value.request.header_value("HX-Request"), "true")
		with page.expect_response(lambda response: urlsplit(response.url).path == "/row") as row_response:
			page.get_by_role("button", name="Add row").click()
		expect(page.locator("#rows > tr > td")).to_have_text(["First", "Second"])
		self.assertEqual(row_response.value.status, 200)
		self.assertNotIn("content-encoding", row_response.value.headers)
