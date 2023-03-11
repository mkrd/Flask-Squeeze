from enum import Enum

from flask import Request, Response, current_app



class Encoding(Enum):
	gzip = "gzip"
	deflate = "deflate"
	br = "br"



class Minifcation(Enum):
	js = "js"
	css = "css"
	html = "html"



def choose_encoding(request: Request):
	if not current_app.config["COMPRESS_FLAG"]:
		return None
	encoding = request.headers.get("Accept-Encoding", "").lower()
	if "br" in encoding:
		return Encoding.br
	elif "deflate" in encoding:
		return Encoding.deflate
	elif "gzip" in encoding:
		return Encoding.gzip
	return None



def choose_minification(response: Response):
	mimetype = response.mimetype
	if (mimetype.endswith("javascript") or mimetype.endswith("json")) and current_app.config["COMPRESS_MINIFY_JS"]:
		return Minifcation.js
	elif mimetype.endswith("css") and current_app.config["COMPRESS_MINIFY_CSS"]:
		return Minifcation.css
	elif mimetype.endswith("html") and current_app.config["COMPRESS_MINIFY_HTML"]:
		return Minifcation.html
	return None
