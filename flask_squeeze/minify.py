from __future__ import annotations

import time
from dataclasses import dataclass

import rcssmin
import rjsmin

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
	Minifies HTML by removing white space and comments.
	Additionally it uses minify_css and minify_js functions
	to minify css in style tags and js in script tags
	respectively.
	"""

	# TODO: Find robust way to minify

	# html_text = html_bytes.decode("utf-8")

	# minified: list[str] = []
	# parser = etree.HTMLParser(recover=False)
	# html_fragments: list[etree._Element] = etree.fromstring(html_text,
	# 	parser=parser
	# )

	# for fragment in html_fragments:
	# 	print("fragment", fragment)
	# 	if isinstance(fragment, str):
	# 		minified.append(fragment)
	# 		continue

	# 	for element in fragment.iter():
	# 		print("element", element, element.tag)
	# 		element: etree._Element = element
	# 		if element.tag in ["pre", "code", "textarea"]:
	# 			pass
	# 		elif element.tag == "style" and element.text:
	# 			element.text = minify_css(element.text)
	# 		elif element.tag == "script" and element.text:
	# 			element.text = minify_js(element.text)
	# 		else:
	# 			if element.text:
	# 				element.text = element.text.strip()
	# 			if element.tail:
	# 				element.tail = element.tail.strip()
	# 		element_bytes: bytes = etree.tostring(element, pretty_print=False)
	# 		minified.append(element_bytes.decode("utf-8"))

	# return "".join(minified)

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
