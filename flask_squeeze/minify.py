import time
from dataclasses import dataclass

import rcssmin
import rjsmin
from flask import Response, request

from flask_squeeze.models import Minification


@dataclass(frozen=True)
class MinificationResult:
	data: bytes
	minification: Minification
	duration: float
	ratio: float


def minify_html(html_text: str) -> str:
	"""
	Minifies HTML by removing white space and comments.
	Additionally it uses minify_css and minify_js functions
	to minify css in style tags and js in script tags
	respectively.
	"""

	# TODO: Find robust way to minify

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

	return html_text


def minify_css(data: str) -> str:
	minified = rcssmin.cssmin(data, keep_bang_comments=False)
	assert isinstance(minified, str)
	return minified


def minify_js(data: str) -> str:
	minified = rjsmin.jsmin(data, keep_bang_comments=False)
	assert isinstance(minified, str)
	return minified


def minify(data: bytes, minify_choice: Minification) -> MinificationResult:
	"""
	Run the minification using the correct minify function and return the minified data.
	"""

	t0 = time.perf_counter()

	if minify_choice == Minification.html:
		minified = minify_html(data.decode("utf-8"))
	elif minify_choice == Minification.css:
		minified = minify_css(data.decode("utf-8"))
	elif minify_choice == Minification.js:
		minified = minify_js(data.decode("utf-8"))
	else:
		raise ValueError(f"Invalid minify choice {minify_choice} at {request.path}")
	minified = minified.encode("utf-8")

	return MinificationResult(
		data=minified,
		minification=minify_choice,
		duration=time.perf_counter() - t0,
		ratio=len(data) / len(minified),
	)


def add_minification_info_headers(response: Response, result: MinificationResult) -> None:
	response.headers["X-Flask-Squeeze-Minify-Duration"] = f"{result.duration * 1000:.1f}ms"
	response.headers["X-Flask-Squeeze-Minify-Ratio"] = f"{result.ratio:.1f}x"
