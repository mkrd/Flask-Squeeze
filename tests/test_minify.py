from pathlib import Path

import pytest

from flask_squeeze.minify import minify, minify_css, minify_html, minify_js


def test_minify_html_preserves_whitespace_sensitive_content() -> None:
	source = (
		b"<!DOCTYPE html><html><head><style>.box { color: red; }</style></head>"
		b"<body><!-- note --><pre>  keep  spaces </pre><textarea>  keep  spaces </textarea><p>Text</p>"
		b"<script>const answer = 42; // note\n</script>"
		b'<script type="application/json">{"key": "value"}</script></body></html>'
	)

	assert minify_html(source) == (
		b"<!DOCTYPE html><style>.box{color:red}</style><pre>  keep  spaces </pre>"
		b"<textarea>  keep  spaces </textarea><p>Text</p><script>const answer=42</script>"
		b'<script type=application/json>{"key": "value"}</script>'
	)


def test_minify_css() -> None:
	assert minify_css(b".box { color: red; margin: 0px; }") == b".box{color:red;margin:0}"


def test_minify_css_preserves_custom_properties_and_data_url() -> None:
	source = b'.x { --gap: 1px; width: calc(100% - var(--gap)); background: url("data:image/svg+xml,%3Csvg%3E"); }'
	assert minify_css(source) == (
		b".x{--gap:1px;width:calc(100% - var(--gap));background:url(data:image/svg+xml,%3Csvg%3E)}"
	)


def test_minify_html_preserves_unicode_and_inline_json() -> None:
	source = '<p>Grüße&nbsp;Welt</p><script type="application/json">{"x": "a  b"}</script>'.encode()
	assert minify_html(source) == (
		'<p>Grüße&nbsp;Welt</p><script type=application/json>{"x": "a  b"}</script>'.encode()
	)


def test_minify_htmx_preserves_unsupported_syntax() -> None:
	source = (Path(__file__).parent / "fixtures" / "htmx.js").read_bytes()

	assert minify_js(source) == source


def test_minify_legacy_javascript() -> None:
	assert minify_js(b"const answer = 42; // comment\n") == b"const answer=42"


def test_minify_private_class_fields_preserves_field_separator() -> None:
	source = b"class Counter {\n  #current = null\n  #queue = []\n}"
	assert b"#current=null;#queue=[]" in minify_js(source)


def test_minify_js_preserves_template_literal_and_private_field() -> None:
	source = b"const x = `Hello ${name}`; class Box { #value = 1; get() { return this.#value; } }"
	assert minify_js(source) == b"const x=`Hello ${name}`;class Box{#value=1;get(){return this.#value}}"


def test_minify_invalid_minification() -> None:
	with pytest.raises(ValueError, match="Unsupported minification: unsupported"):
		minify(b"test data", "unsupported")  # type: ignore[arg-type]
