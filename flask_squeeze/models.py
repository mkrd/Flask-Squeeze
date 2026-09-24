from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from werkzeug.datastructures import Accept
from werkzeug.http import parse_accept_header

if TYPE_CHECKING:
	from flask import Config
	from werkzeug.datastructures import Headers


class ResourceType(Enum):
	static = "static"
	dynamic = "dynamic"


class Encoding(Enum):
	gzip = "gzip"
	deflate = "deflate"
	br = "br"

	@classmethod
	def get_from_headers_and_config(
		cls,
		headers: Headers,
		config: Config,
	) -> Encoding | None:
		"""
		If the client supports brotli, gzip, or deflate, return the best encoding.
		If the client does not accept any of these encodings, or if the config
		variable SQUEEZE_COMPRESS is False, return None.
		"""
		if not config.get("SQUEEZE_COMPRESS"):
			return None
		accepted = parse_accept_header(headers.get("Accept-Encoding"), Accept)
		best: Encoding | None = None
		best_quality = 0.0
		for encoding in (cls.br, cls.deflate, cls.gzip):
			quality = accepted.quality(encoding.value)
			if quality > best_quality:
				best = encoding
				best_quality = quality
		return best


class Minification(Enum):
	js = "js"
	css = "css"
	html = "html"

	@classmethod
	def get_from_mimetype_and_config(
		cls,
		mimetype: str | None,
		config: Config,
	) -> Minification | None:
		"""
		Based on the response mimetype:
		- `javascript` and `SQUEEZE_MINIFY_JS=True`: return `Minification.js`
		- `css` and `SQUEEZE_MINIFY_CSS=True`: return `Minification.css`
		-  `html` and `SQUEEZE_MINIFY_HTML=True`: return `Minification.html`
		- Otherwise, return `None`
		"""
		if mimetype is None:
			return None
		if mimetype.endswith("javascript") and config.get("SQUEEZE_MINIFY_JS"):
			return cls.js
		if mimetype.endswith("css") and config.get("SQUEEZE_MINIFY_CSS"):
			return cls.css
		if mimetype.endswith("html") and config.get("SQUEEZE_MINIFY_HTML"):
			return cls.html
		return None
