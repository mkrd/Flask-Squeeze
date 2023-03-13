import rcssmin
import rjsmin
from lxml import etree
from lxml.html import fragments_fromstring


def minify_html(html_text: str) -> str:
	"""
		Minifies HTML by removing white space and comments.
		Additionally it uses minify_css and minify_js functions
		to minify css in style tags and js in script tags
		respectively.
	"""
	try:
		minified: list[str] = []
		parser = etree.HTMLParser(recover=False)
		html_fragments: list[etree._Element] = fragments_fromstring(html_text,
			parser=parser
		)

		for fragment in html_fragments:
			if isinstance(fragment, str):
				minified.append(fragment)
				continue

			for element in fragment.iter():
				element: etree._Element = element
				print(element)
				print(element.text)
				print(element.tail)
				if element.tag in ["pre", "code", "textarea"]:
					pass
				elif element.tag == "style":
					element.text = minify_css(element.text)
				elif element.tag == "script":
					element.text = minify_js(element.text)
				else:
					if element.text:
						element.text = element.text.strip()
					if element.tail:
						element.tail = element.tail.strip()
				element_bytes: bytes = etree.tostring(element, pretty_print=False)
				minified.append(element_bytes.decode("utf-8"))

		return "".join(minified)

	except Exception as e:
		return html_text



def minify_css(data: str) -> str:
	return rcssmin.cssmin(data, keep_bang_comments=False)



def minify_js(data: str) -> str:
	return rjsmin.jsmin(data, keep_bang_comments=False)



test_html = '''

		Leading and trailing white space is removed
		<a href="fo&quot;o">&lt;</a>
		<a href="fo&quot;o">&lt;</a>
		<div cl="lol">
			lel
			<pre>
				lol
			</pre>

		</div>
		<a href="fo&quot;o">&lt;</a>

		<a href="fo&quot;o">&lt;</a>

		Trailer

'''





broken_html = "<html><head><title>test<body><h1>page title</h3>"
