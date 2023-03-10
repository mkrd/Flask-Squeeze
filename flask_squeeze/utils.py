from flask import Request



def get_requested_encoding(request: Request) -> str:
	accepted_encodings = request.headers.get("Accept-Encoding", "").lower()
	if "br" in accepted_encodings:
		return "br"
	if "deflate" in accepted_encodings:
		return "deflate"
	if "gzip" in accepted_encodings:
		return "gzip"
	return "none"



def is_js(mimetype: str) -> bool:
	return mimetype.endswith("javascript") or mimetype.endswith("json")



def is_css(mimetype: str) -> bool:
	return mimetype.endswith("css")



def is_html(mimetype: str) -> bool:
	return mimetype.endswith("html")
