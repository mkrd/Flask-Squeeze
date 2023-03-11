from flask import Request, Response, current_app



class RequestedEncoding:
	def __init__(self, request: Request) -> None:
		encoding = request.headers.get("Accept-Encoding", "").lower()
		if "br" in encoding:
			self.value = "br"
		elif "deflate" in encoding:
			self.value = "deflate"
		elif "gzip" in encoding:
			self.value = "gzip"
		else:
			self.value = "none"

	@property
	def is_br(self) -> bool:
		return self.value == "br"

	@property
	def is_deflate(self) -> bool:
		return self.value == "deflate"

	@property
	def is_gzip(self) -> bool:
		return self.value == "gzip"

	@property
	def none(self) -> bool:
		return self.value == "none"

	@property
	def should_compress(self) -> bool:
		return not self.none and current_app.config["COMPRESS_FLAG"]



class ResourceType:
	def __init__(self, response: Response) -> None:
		mimetype = response.mimetype
		if mimetype.endswith("javascript") or mimetype.endswith("json"):
			self.value = "js"
		elif mimetype.endswith("css"):
			self.value = "css"
		elif mimetype.endswith("html"):
			self.value = "html"
		else:
			self.value = "other"

	@property
	def is_js(self) -> bool:
		return self.value == "js"

	@property
	def is_css(self) -> bool:
		return self.value == "css"

	@property
	def is_html(self) -> bool:
		return self.value == "html"

	@property
	def other(self) -> bool:
		return self.value == "other"

	@property
	def should_minify(self) -> bool:
		return (
			(self.is_html and current_app.config["COMPRESS_MINIFY_HTML"]) or
			(self.is_css and current_app.config["COMPRESS_MINIFY_CSS"]) or
			(self.is_js and current_app.config["COMPRESS_MINIFY_JS"])
		)
