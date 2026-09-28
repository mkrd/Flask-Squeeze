from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, Response
from playwright.sync_api import Route, expect, sync_playwright

from flask_squeeze import Squeeze


def test_htmx_request_and_swap_in_browser() -> None:
	app = Flask(__name__, static_folder=str(Path(__file__).parent / "fixtures"), static_url_path="/static")
	app.config.update(SQUEEZE_MIN_SIZE=0)

	@app.get("/")
	def index() -> Response:
		return Response(
			'<script src="/static/htmx.js"></script>'
			'<button hx-get="/fragment" hx-target="#result">Load</button>'
			'<div id="result"></div>',
			mimetype="text/html",
		)

	@app.get("/fragment")
	def fragment() -> Response:
		return Response("<span>Loaded</span>", mimetype="text/html")

	Squeeze(app)
	client = app.test_client()
	paths: list[str] = []

	def serve(route: Route) -> None:
		path = urlsplit(route.request.url).path
		paths.append(path)
		response = client.get(path)
		route.fulfill(status=response.status_code, body=response.data, content_type=response.content_type)

	with sync_playwright() as playwright:
		browser = playwright.chromium.launch()
		try:
			page = browser.new_page()
			page.route("**/*", serve)
			page.goto("http://squeeze.test/")
			assert page.evaluate("typeof htmx") == "object"
			page.get_by_role("button", name="Load").click()
			assert "/fragment" in paths
			expect(page.locator("#result")).to_have_text("Loaded")
		finally:
			browser.close()
