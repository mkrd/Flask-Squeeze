from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Union

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


class Minification(Enum):
	js = "js"
	css = "css"
	html = "html"


@dataclass(frozen=True)
class CacheKey:
	path: str
	encoding: Encoding | None

	@property
	def normalized(self) -> str:
		return self.path.replace("/", "_") + (self.encoding.value if self.encoding else "none")


def choose_encoding_from_headers_and_config(
	headers: Headers,
	config: Config,
) -> Union[Encoding, None]:
	"""
	If the client supports brotli, gzip, or deflate, return the best encoding.
	If the client does not accept any of these encodings, or if the config
	variable SQUEEZE_COMPRESS is False, return None.
	"""
	if not config.get("SQUEEZE_COMPRESS"):
		return None
	encoding = headers.get("Accept-Encoding", "").lower()
	if "br" in encoding:
		return Encoding.br
	if "deflate" in encoding:
		return Encoding.deflate
	if "gzip" in encoding:
		return Encoding.gzip
	return None


def choose_minification_from_mimetype_and_config(
	mimetype: Union[str, None],
	config: Config,
) -> Union[Minification, None]:
	"""
	Based on the response mimetype:
	- `js` or `json`, and `SQUEEZE_MINIFY_JS=True`: return `Minification.js`
	- `css` and `SQUEEZE_MINIFY_CSS=True`: return `Minification.css`
	-  `html` and `SQUEEZE_MINIFY_HTML=True`: return `Minification.html`
	- Otherwise, return `None`
	"""
	if mimetype is None:
		return None
	is_js_or_json = mimetype.endswith(("javascript", "json"))
	if is_js_or_json and config.get("SQUEEZE_MINIFY_JS"):
		return Minification.js
	if mimetype.endswith("css") and config.get("SQUEEZE_MINIFY_CSS"):
		return Minification.css
	if mimetype.endswith("html") and config.get("SQUEEZE_MINIFY_HTML"):
		return Minification.html
	return None
