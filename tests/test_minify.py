import unittest
from pathlib import Path
from unittest.mock import patch

from flask_squeeze.minify import is_document, minify, minify_css, minify_html, minify_js
from flask_squeeze.plan import Minification
from flask_squeeze.stats import OperationError, OperationStatus

BOM = "\N{ZERO WIDTH NO-BREAK SPACE}".encode()


class MinifyTest(unittest.TestCase):
	def test_empty_minified_body_has_finite_stats(self) -> None:
		cases = (
			(Minification.html, b"<!-- comment -->"),
			(Minification.css, b"/* comment */"),
			(Minification.js, b"// comment\n"),
		)
		for minification, comment in cases:
			for source in (b"", comment):
				with self.subTest(minification=minification, source=source):
					body, stats = minify(source, minification)
					self.assertEqual(body, b"")
					self.assertEqual(stats.size_ratio, 1.0)
					self.assertIn("ratio=1.0x", stats.info_headers["X-Flask-Squeeze-Minify"])

	def test_byte_order_mark_is_dropped(self) -> None:
		cases = (
			(Minification.html, b"<!DOCTYPE html><p>x</p>", b"<!DOCTYPE html><p>x"),
			(Minification.css, b".a { color: red; }", b".a{color:red}"),
			(Minification.js, b"const a = 1;", b"const a=1"),
		)
		for minification, source, expected in cases:
			with self.subTest(minification=minification):
				self.assertEqual(minify(BOM + source, minification)[0], expected)

	def test_invalid_utf8_reports_failure(self) -> None:
		for minification in Minification:
			with self.subTest(minification=minification):
				original = "\N{LATIN SMALL LETTER E WITH ACUTE}".encode("latin-1")
				body, stats = minify(original, minification)
				self.assertEqual(body, original)
				self.assertEqual(stats.status, OperationStatus.failed)
				self.assertEqual(stats.error, OperationError.invalid_utf8)
				self.assertIsNone(stats.after_bytes)
				self.assertIn("status=minification_failed", stats.info_headers["X-Flask-Squeeze-Minify"])
				self.assertNotIn("ratio=", stats.info_headers["X-Flask-Squeeze-Minify"])

	def test_minify_html_preserves_whitespace_sensitive_content(self) -> None:
		source = (
			"<!DOCTYPE html><html><head><style>.box { color: red; }</style></head>"
			"<body><!-- note --><pre>  keep  spaces </pre><textarea>  keep  spaces </textarea><p>Text</p>"
			"<script>const answer = 42; // note\n</script>"
			'<script type="application/json">{"key": "value"}</script></body></html>'
		)

		self.assertEqual(
			minify_html(source),
			"<!DOCTYPE html><style>.box{color:red}</style><pre>  keep  spaces </pre>"
			"<textarea>  keep  spaces </textarea><p>Text</p><script>const answer=42</script>"
			'<script type=application/json>{"key": "value"}</script>',
		)

	def test_is_document(self) -> None:
		cases = [
			("<!DOCTYPE html><p>x</p>", True),
			("<!doctype HTML>", True),
			("\n  <!-- generated -->\n<!DOCTYPE html>", True),
			("<!-- ended by --!><html>", True),
			('<?xml version="1.0"?>\n<!DOCTYPE html>', True),
			("<HTML lang=en>", True),
			("<head><title>t</title></head>", True),
			("<body class=dark>", True),
			("<header>x</header>", False),
			("<htmlx>", False),
			("<tr><td>a</td></tr>", False),
			("text <html>", False),
			("\N{NO-BREAK SPACE}<html>", False),
			("<!-- only a comment -->", False),
			("", False),
		]
		for source, expected in cases:
			with self.subTest(source=source):
				self.assertIs(is_document(source), expected)

	def test_minify_html_keeps_document_level_tags(self) -> None:
		cases = [
			("<!-- generated -->\n<!DOCTYPE html><p>x</p>", "<!DOCTYPE html><p>x"),
			('<?xml version="1.0"?>\n<!DOCTYPE html><p>x</p>', "<!DOCTYPE html><p>x"),
			("<HTML lang=en><p>x</p>", "<html lang=en><p>x"),
			("<head><title>t</title></head><p>x</p>", "<title>t</title><p>x"),
			("<body class=dark><p>x</p></body>", "<body class=dark><p>x"),
		]
		for source, expected in cases:
			with self.subTest(source=source):
				self.assertEqual(minify_html(source), expected)

	def test_minify_html_keeps_body_fragments(self) -> None:
		cases = [
			("<span>Loaded</span>", "<span>Loaded</span>"),
			("<span>a</span> <span>b</span>", "<span>a</span> <span>b</span>"),
			("<header>x</header>", "<header>x</header>"),
			("<li>x</li>", "<li>x</li>"),
			("<p>a</p><!-- comment --><p>b</p>", "<p>a</p><p>b</p>"),
			("<p>a</p>b", "<p>a</p>b"),
			('<div hx-swap-oob="true" id="a">x</div>', "<div hx-swap-oob=true id=a>x</div>"),
		]
		for source, expected in cases:
			with self.subTest(source=source):
				self.assertEqual(minify_html(source), expected)

	def test_minify_html_keeps_table_fragments(self) -> None:
		# htmx swaps fragments like these into existing tables. Parsed as a document, the
		# HTML parser would drop table tags outside a <table>, leaving only their text.
		cases = [
			("<tr><td>a</td></tr>", "<tr><td>a</tr>"),
			("<td>a</td><td>b</td>", "<td>a</td><td>b</td>"),
			("<thead><tr><th>h</th></tr></thead>", "<thead><tr><th>h</thead>"),
		]
		for source, expected in cases:
			with self.subTest(source=source):
				self.assertEqual(minify_html(source), expected)

	def test_minify_css(self) -> None:
		self.assertEqual(minify_css(".box { color: red; margin: 0px; }"), ".box{color:red;margin:0}")

	def test_minify_css_preserves_custom_properties_and_data_url(self) -> None:
		source = '.x { --gap: 1px; width: calc(100% - var(--gap)); background: url("data:image/svg+xml,%3Csvg%3E"); }'
		self.assertEqual(
			minify_css(source),
			".x{--gap:1px;width:calc(100% - var(--gap));background:url(data:image/svg+xml,%3Csvg%3E)}",
		)

	def test_minify_html_preserves_unicode_and_inline_json(self) -> None:
		source = '<p>Grüße&nbsp;Welt</p><script type="application/json">{"x": "a  b"}</script>'
		self.assertEqual(
			minify_html(source),
			'<p>Grüße&nbsp;Welt</p><script type=application/json>{"x": "a  b"}</script>',
		)

	def test_minify_htmx_preserves_unsupported_syntax(self) -> None:
		source = (Path(__file__).parent / "fixtures" / "htmx.js").read_bytes()

		body, stats = minify(source, Minification.js)
		self.assertEqual(body, source)
		self.assertEqual(stats.status, OperationStatus.failed)
		self.assertEqual(stats.error, OperationError.javascript_parse_error)

	def test_larger_output_is_not_applied(self) -> None:
		for minification, target in (
			(Minification.html, "flask_squeeze.minify.minify_html"),
			(Minification.css, "flask_squeeze.minify.minify_css"),
			(Minification.js, "flask_squeeze.minify.minify_js"),
		):
			with self.subTest(minification=minification), patch(target, return_value="larger output"):
				body, stats = minify(b"input", minification)
				self.assertEqual(body, b"input")
				self.assertEqual(stats.status, OperationStatus.skipped_larger)
				self.assertEqual(stats.before_bytes, 5)
				self.assertEqual(stats.after_bytes, 13)
				self.assertIn("status=skipped_minified_too_large", stats.info_headers["X-Flask-Squeeze-Minify"])
				self.assertNotIn("ratio=", stats.info_headers["X-Flask-Squeeze-Minify"])

	def test_sizes_count_utf8_bytes(self) -> None:
		body, stats = minify("<p>Grüße</p><!-- comment -->".encode(), Minification.html)
		self.assertEqual(stats.before_bytes, 30)
		self.assertEqual(stats.after_bytes, len(body))
		self.assertGreater(stats.after_bytes or 0, len(body.decode()))
		self.assertIn(f"before=30; after={len(body)};", stats.info_headers["X-Flask-Squeeze-Minify"])

	def test_equal_size_output_is_applied(self) -> None:
		body, stats = minify(b"<span>x</span>", Minification.html)
		self.assertEqual(body, b"<span>x</span>")
		self.assertEqual(stats.status, OperationStatus.applied)

	def test_minify_legacy_javascript(self) -> None:
		self.assertEqual(minify_js("const answer = 42; // comment\n"), "const answer=42")

	def test_minify_private_class_fields_preserves_field_separator(self) -> None:
		source = "class Counter {\n  #current = null\n  #queue = []\n}"
		self.assertIn("#current=null;#queue=[]", minify_js(source))

	def test_minify_js_preserves_template_literal_and_private_field(self) -> None:
		source = "const x = `Hello ${name}`; class Box { #value = 1; get() { return this.#value; } }"
		self.assertEqual(minify_js(source), "const x=`Hello ${name}`;class Box{#value=1;get(){return this.#value}}")
