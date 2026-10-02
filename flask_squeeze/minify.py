from __future__ import annotations

import time
from dataclasses import dataclass

from turbohtml import Html, Minify, TokenType, parse_fragment, tokenize
from turbohtml.clean import CSSMinify, JSMinify
from turbohtml.clean import minify as minify_document
from turbohtml.clean import minify_css as minify_stylesheet
from turbohtml.clean import minify_js as minify_javascript

from .plan import Minification

JS_OPTIONS = JSMinify(mangle=False, fold=False)
HTML_OPTIONS = Minify(minify_css=CSSMinify(), minify_js=JS_OPTIONS)
HTML_LAYOUT = Html(layout=HTML_OPTIONS)
HTML_WHITESPACE = " \t\n\f\r"
DOCUMENT_TAGS = frozenset({"html", "head", "body"})


@dataclass(frozen=True)
class MinificationStats:
	duration_seconds: float
	size_ratio: float
	"""Original size divided by minified size"""

	@property
	def info_headers(self) -> dict[str, str]:
		value = "; ".join(
			[
				f"ratio={self.size_ratio:.1f}x",
				f"duration={self.duration_seconds * 1000:.1f}ms",
			],
		)
		return {"X-Flask-Squeeze-Minify": value}


def is_document(html: str) -> bool:
	"""Whether the first tag, after whitespace and comments, is a doctype, <html>, <head> or <body>."""
	for token in tokenize(html):
		if token.type is TokenType.COMMENT:
			continue
		if token.type is TokenType.TEXT and token.data is not None and not token.data.strip(HTML_WHITESPACE):
			continue
		return token.type is TokenType.DOCTYPE or (token.type is TokenType.START_TAG and token.tag in DOCUMENT_TAGS)
	return False


def minify_html(html: str) -> str:
	if is_document(html):
		return minify_document(html, HTML_OPTIONS)
	# Parsed as a document, fragments such as table rows for htmx would lose the tags that are invalid
	# outside their parent. A template accepts any content, like the one htmx parses fragments in.
	fragment = parse_fragment(html, "template")
	return "".join(node.serialize(HTML_LAYOUT) for node in fragment.children)


def minify_css(css: str) -> str:
	return minify_stylesheet(css)


def minify_js(js: str) -> str:
	return minify_javascript(js, JS_OPTIONS, on_error="passthrough")


def minify(body: bytes, minification: Minification) -> tuple[bytes, MinificationStats]:
	"""Minify UTF-8 text. Raises UnicodeDecodeError for anything else."""
	start_time = time.perf_counter()

	# utf-8-sig drops a leading BOM, which the HTML parser would otherwise read as text before the doctype
	text = body.decode("utf-8-sig")
	match minification:
		case Minification.html:
			minified_text = minify_html(text)
		case Minification.css:
			minified_text = minify_css(text)
		case Minification.js:
			minified_text = minify_js(text)
	minified_body = minified_text.encode("utf-8")

	size_ratio = len(body) / len(minified_body) if len(minified_body) > 0 else 1.0

	return minified_body, MinificationStats(
		duration_seconds=time.perf_counter() - start_time,
		size_ratio=size_ratio,
	)
