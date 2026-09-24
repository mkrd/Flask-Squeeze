from __future__ import annotations

import time
from dataclasses import dataclass

from turbohtml import Minify
from turbohtml.clean import CSSMinify, JSMinify
from turbohtml.clean import minify as minify_document
from turbohtml.clean import minify_css as minify_stylesheet
from turbohtml.clean import minify_js as minify_javascript

from .models import Minification


@dataclass(frozen=True)
class MinificationInfo:
	minification: Minification
	duration: float
	ratio: float

	@property
	def headers(self) -> dict[str, str]:
		value = "; ".join(
			[
				f"ratio={self.ratio:.1f}x",
				f"duration={self.duration * 1000:.1f}ms",
			],
		)
		return {"X-Flask-Squeeze-Minify": value}


def minify_html(html_bytes: bytes) -> bytes:
	options = Minify(minify_css=CSSMinify(), minify_js=JSMinify(mangle=False, fold=False))
	return minify_document(html_bytes.decode("utf-8"), options).encode("utf-8")


def minify_css(data: bytes) -> bytes:
	return minify_stylesheet(data.decode("utf-8")).encode("utf-8")


def minify_js(data: bytes) -> bytes:
	minified = minify_javascript(data.decode("utf-8"), JSMinify(mangle=False, fold=False), on_error="passthrough")
	return minified.encode("utf-8")


def minify(data: bytes, minification: Minification) -> tuple[bytes, MinificationInfo]:
	"""
	Run the minification using the correct minify function and return the minified data.
	"""

	t0 = time.perf_counter()

	if minification is Minification.html:
		minified_data = minify_html(data)
	elif minification is Minification.css:
		minified_data = minify_css(data)
	elif minification is Minification.js:
		minified_data = minify_js(data)
	else:
		msg = f"Unsupported minification: {minification}"
		raise ValueError(msg)

	ratio = len(data) / len(minified_data) if len(minified_data) > 0 else 1.0

	return minified_data, MinificationInfo(
		minification=minification,
		duration=time.perf_counter() - t0,
		ratio=ratio,
	)
