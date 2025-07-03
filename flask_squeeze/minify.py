from __future__ import annotations

import time
from dataclasses import dataclass

import rcssmin
import rjsmin
import minify_html as minifyhtml

from .models import Minification


@dataclass(frozen=True)
class MinificationInfo:
	minification: Minification
	duration: float
	ratio: float

	@property
	def headers(self) -> dict:
		value = "; ".join(
			[
				f"ratio={self.ratio:.1f}x",
				f"duration={self.duration * 1000:.1f}ms",
			],
		)
		return {"X-Flask-Squeeze-Minify": value}


def minify_html(html_bytes: bytes) -> bytes:
	"""
	Minifies HTML by using minify-html
	"""

	# Decode from utf-8
	html_text = html_bytes.decode()

	# Minify using minify_html and re-encode back into bytes
	html_bytes = minifyhtml.minify(html_text).encode()

	return html_bytes


def minify_css(data: bytes) -> bytes:
	minified = rcssmin.cssmin(data)
	assert isinstance(minified, bytes)
	return minified


def minify_js(data: bytes) -> bytes:
	minified = rjsmin.jsmin(data)
	assert isinstance(minified, bytes)
	return minified


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
