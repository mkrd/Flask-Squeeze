from __future__ import annotations

import time
from dataclasses import dataclass

from turbohtml import Html, Minify, TokenType, parse_fragment, tokenize
from turbohtml.clean import CSSMinify, JSMinify
from turbohtml.clean import minify as minify_document
from turbohtml.clean import minify_css as minify_stylesheet
from turbohtml.clean import minify_js as minify_javascript

from .plan import Minification
from .stats import InfoStatus, OperationError, OperationStats, OperationStatus

JS_OPTIONS = JSMinify(mangle=False, fold=False)
CSS_OPTIONS = CSSMinify()
HTML_OPTIONS = Minify(minify_css=CSS_OPTIONS, minify_js=JS_OPTIONS)
HTML_LAYOUT = Html(layout=HTML_OPTIONS)
HTML_WHITESPACE = " \t\n\f\r"
DOCUMENT_TAGS = frozenset({"html", "head", "body"})


def minification_options_signature() -> tuple[str, ...]:
	return (
		repr(JS_OPTIONS),
		repr(CSS_OPTIONS),
		str(HTML_OPTIONS.collapse_whitespace),
		str(HTML_OPTIONS.omit_optional_tags),
		str(HTML_OPTIONS.unquote_attributes),
		str(HTML_OPTIONS.strip_comments),
		repr(HTML_OPTIONS.minify_js),
		repr(HTML_OPTIONS.minify_css),
	)


@dataclass(frozen=True)
class MinificationStats(OperationStats):
	@property
	def info_headers(self) -> dict[str, str]:
		fields = self.info_fields(
			success=InfoStatus.minified,
			failure=InfoStatus.minification_failed,
			skipped=InfoStatus.skipped_minified_too_large,
		)
		value = "; ".join(fields)
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
	return minify_stylesheet(css, CSS_OPTIONS)


def minify_js(js: str) -> str:
	return minify_javascript(js, JS_OPTIONS, on_error="raise")


def _failed_minification(body: bytes, start_time: float, error: OperationError) -> tuple[bytes, MinificationStats]:
	return body, MinificationStats(
		duration_seconds=time.perf_counter() - start_time,
		before_bytes=len(body),
		after_bytes=None,
		error=error,
	)


def minify(body: bytes, minification: Minification) -> tuple[bytes, MinificationStats]:
	"""Minify UTF-8 text, retaining the input on parsing failure or size increase."""
	start_time = time.perf_counter()

	# utf-8-sig drops a leading BOM, which the HTML parser would otherwise read as text before the doctype
	try:
		text = body.decode("utf-8-sig")
	except UnicodeDecodeError:
		return _failed_minification(body, start_time, OperationError.invalid_utf8)
	match minification:
		case Minification.html:
			minified_text = minify_html(text)
		case Minification.css:
			minified_text = minify_css(text)
		case Minification.js:
			try:
				minified_text = minify_js(text)
			except ValueError:
				return _failed_minification(body, start_time, OperationError.javascript_parse_error)
	minified_body = minified_text.encode("utf-8")

	stats = MinificationStats(
		duration_seconds=time.perf_counter() - start_time,
		before_bytes=len(body),
		after_bytes=len(minified_body),
	)
	return (minified_body if stats.status is OperationStatus.applied else body), stats
