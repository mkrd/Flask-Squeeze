from flask import Request, Response




def get_requested_encoding_str(request: Request) -> str:
	accepted_encodings = request.headers.get("Accept-Encoding", "").lower()
	if "br" in accepted_encodings:
		return "br"
	if "deflate" in accepted_encodings:
		return "deflate"
	if "gzip" in accepted_encodings:
		return "gzip"
	return "none"


class RequestedEncoding:
	def __init__(self, request: Request):
		self.encoding = request.headers.get("Accept-Encoding", "").lower()

	@property
	def is_br(self) -> bool:
		return "br" in self.encoding

	@property
	def is_deflate(self) -> bool:
		return "deflate" in self.encoding

	@property
	def is_gzip(self) -> bool:
		return "gzip" in self.encoding

	@property
	def none(self) -> bool:
		return not (self.is_br or self.is_deflate or self.is_gzip)


def get_requested_encoding(request: Request) -> RequestedEncoding:
	return RequestedEncoding(request)



class ResourceType:
	def __init__(self, mimetype: str):
		self.mimetype = mimetype

	@property
	def is_js(self) -> bool:
		return self.mimetype.endswith("javascript") or self.mimetype.endswith("json")

	@property
	def is_css(self) -> bool:
		return self.mimetype.endswith("css")

	@property
	def is_html(self) -> bool:
		return self.mimetype.endswith("html")

	@property
	def other(self) -> bool:
		return not (self.is_js or self.is_css or self.is_html)



def get_resource_type(response: Response) -> ResourceType:
	return ResourceType(response.mimetype)
