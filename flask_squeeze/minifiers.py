from html.parser import HTMLParser
import rjsmin
import rcssmin


class MinifyHTMLParser(HTMLParser):
	def __init__(self):
		super().__init__()
		self.minified_html = []

	def write(self, data: str) -> None:
		self.minified_html.append(data)

	def get_minified_html(self) -> str:
		return "".join(self.minified_html)

	def handle_decl(self, decl: str) -> None:
		self.write(f"<!{decl}>")

	def unknown_decl(self, data: str) -> None:
		self.write(f"<!{data}>")

	def handle_pi(self, data):
		self.write(f"<?{data}>")

	def handle_startendtag(self, tag, attrs):
		self.add_tag(tag, attrs, "/>")

	def handle_entityref(self, name):
		self.write(f"&{name};")

	def handle_charref(self, name):
		self.write(f"&#x{name};")

	def handle_starttag(self, tag, attrs):
		self.add_tag(tag, attrs, ">")

	# TODO Rename this here and in `handle_startendtag` and `handle_starttag`
	def add_tag(self, tag, attrs, end_tag):
		self.write(f"<{tag}")
		for attr in attrs:
			self.write(f' {attr[0]}')
			if attr[1] is not None:
				self.write(f'="{attr[1]}"')
		self.write(end_tag)

	def handle_endtag(self, tag):
		self.write(f"</{tag}>")

	def handle_data(self, data):
		if self.lasttag == "style":
			self.write(minify_css(data).strip())
		elif self.lasttag == "script":
			self.write(minify_js(data).strip())
		elif self.lasttag in ["textarea", "pre", "code"]:
			self.write(data)
		else:
			self.write(data.strip())



def minify_html(html_text: str) -> str:
	"""
	Minifies HTML by removing white space and comments.
	Additionally it uses minify_css and minify_js functions
	to minify css in style tags and js in script tags
	respectively.
	"""

	parser = MinifyHTMLParser()
	parser.feed(html_text)
	return parser.get_minified_html()



def minify_css(data: str) -> str:
	return rcssmin.cssmin(data, keep_bang_comments=False)



def minify_js(data: str) -> str:
	return rjsmin.jsmin(data, keep_bang_comments=False)
