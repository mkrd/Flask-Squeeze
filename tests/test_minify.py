import unittest
from pathlib import Path

from flask_squeeze.minify import minify, minify_css, minify_html, minify_js
from flask_squeeze.plan import Minification


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

	def test_minify_html_preserves_whitespace_sensitive_content(self) -> None:
		source = (
			b"<!DOCTYPE html><html><head><style>.box { color: red; }</style></head>"
			b"<body><!-- note --><pre>  keep  spaces </pre><textarea>  keep  spaces </textarea><p>Text</p>"
			b"<script>const answer = 42; // note\n</script>"
			b'<script type="application/json">{"key": "value"}</script></body></html>'
		)

		self.assertEqual(
			minify_html(source),
			b"<!DOCTYPE html><style>.box{color:red}</style><pre>  keep  spaces </pre>"
			b"<textarea>  keep  spaces </textarea><p>Text</p><script>const answer=42</script>"
			b'<script type=application/json>{"key": "value"}</script>',
		)

	def test_minify_css(self) -> None:
		self.assertEqual(minify_css(b".box { color: red; margin: 0px; }"), b".box{color:red;margin:0}")

	def test_minify_css_preserves_custom_properties_and_data_url(self) -> None:
		source = b'.x { --gap: 1px; width: calc(100% - var(--gap)); background: url("data:image/svg+xml,%3Csvg%3E"); }'
		self.assertEqual(
			minify_css(source),
			b".x{--gap:1px;width:calc(100% - var(--gap));background:url(data:image/svg+xml,%3Csvg%3E)}",
		)

	def test_minify_html_preserves_unicode_and_inline_json(self) -> None:
		source = '<p>Grüße&nbsp;Welt</p><script type="application/json">{"x": "a  b"}</script>'.encode()
		self.assertEqual(
			minify_html(source),
			'<p>Grüße&nbsp;Welt</p><script type=application/json>{"x": "a  b"}</script>'.encode(),
		)

	def test_minify_htmx_preserves_unsupported_syntax(self) -> None:
		source = (Path(__file__).parent / "fixtures" / "htmx.js").read_bytes()

		self.assertEqual(minify_js(source), source)

	def test_minify_legacy_javascript(self) -> None:
		self.assertEqual(minify_js(b"const answer = 42; // comment\n"), b"const answer=42")

	def test_minify_private_class_fields_preserves_field_separator(self) -> None:
		source = b"class Counter {\n  #current = null\n  #queue = []\n}"
		self.assertIn(b"#current=null;#queue=[]", minify_js(source))

	def test_minify_js_preserves_template_literal_and_private_field(self) -> None:
		source = b"const x = `Hello ${name}`; class Box { #value = 1; get() { return this.#value; } }"
		self.assertEqual(minify_js(source), b"const x=`Hello ${name}`;class Box{#value=1;get(){return this.#value}}")
