import rcssmin
import rjsmin


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
	return rcssmin.cssmin(data, keep_bang_comments=False)



def minify_js(data: str) -> str:
	return rjsmin.jsmin(data, keep_bang_comments=False)
