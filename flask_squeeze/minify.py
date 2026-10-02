from __future__ import annotations

import time
from dataclasses import dataclass

from turbohtml import Minify
from turbohtml.clean import CSSMinify, JSMinify
from turbohtml.clean import minify as minify_document
from turbohtml.clean import minify_css as minify_stylesheet
from turbohtml.clean import minify_js as minify_javascript

from .plan import Minification


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


def minify_html(body: bytes) -> bytes:
	html_options = Minify(minify_css=CSSMinify(), minify_js=JSMinify(mangle=False, fold=False))
	return minify_document(body.decode("utf-8"), html_options).encode("utf-8")


def minify_css(body: bytes) -> bytes:
	return minify_stylesheet(body.decode("utf-8")).encode("utf-8")


def minify_js(body: bytes) -> bytes:
	minified = minify_javascript(body.decode("utf-8"), JSMinify(mangle=False, fold=False), on_error="passthrough")
	return minified.encode("utf-8")


def minify(body: bytes, minification: Minification) -> tuple[bytes, MinificationStats]:
	start_time = time.perf_counter()

	match minification:
		case Minification.html:
			minified_body = minify_html(body)
		case Minification.css:
			minified_body = minify_css(body)
		case Minification.js:
			minified_body = minify_js(body)

	size_ratio = len(body) / len(minified_body) if len(minified_body) > 0 else 1.0

	return minified_body, MinificationStats(
		duration_seconds=time.perf_counter() - start_time,
		size_ratio=size_ratio,
	)
