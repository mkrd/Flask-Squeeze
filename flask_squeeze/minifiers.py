from html.parser import HTMLParser
import rjsmin
import rcssmin


class MinifyHTMLParser(HTMLParser):
	def __init__(self):
		super().__init__()
		self.minified_html = ""

	def handle_decl(self, decl: str) -> None:
		self.minified_html += f"<!{decl}>"

	def unknown_decl(self, data: str) -> None:
		self.minified_html += f"<!{data}>"

	def handle_pi(self, data):
		self.minified_html += f"<?{data}>"

	def handle_startendtag(self, tag, attrs):
		self.add_tag(tag, attrs, "/>")

	def handle_entityref(self, name):
		self.minified_html += f"&{name};"

	def handle_charref(self, name):
		self.minified_html += f"&#x{name};"

	def handle_starttag(self, tag, attrs):
		self.add_tag(tag, attrs, ">")

	# TODO Rename this here and in `handle_startendtag` and `handle_starttag`
	def add_tag(self, tag, attrs, end_tag):
		self.minified_html += f"<{tag}"
		for attr in attrs:
			self.minified_html += f' {attr[0]}'
			if attr[1] is not None:
				self.minified_html += f'="{attr[1]}"'
		self.minified_html += end_tag

	def handle_endtag(self, tag):
		self.minified_html += f"</{tag}>"

	def handle_data(self, data):
		if self.lasttag == "style":
			self.minified_html += minify_css(data).strip()
		elif self.lasttag == "script":
			self.minified_html += minify_js(data).strip()
		elif self.lasttag in ["textarea", "pre", "code"]:
			self.minified_html += data
		else:
			self.minified_html += data.strip()



def minify_html(html_text: str) -> str:
	"""
	Minifies HTML by removing white space and comments.
	Additionally it uses minify_css and minify_js functions
	to minify css in style tags and js in script tags
	respectively.
	"""

	parser = MinifyHTMLParser()
	parser.feed(html_text)
	return parser.minified_html



def minify_css(data: str) -> str:
	return rcssmin.cssmin(data, keep_bang_comments=False)



def minify_js(data: str) -> str:
	return rjsmin.jsmin(data, keep_bang_comments=False)
