from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ResourceType(Enum):
	static = "static"
	dynamic = "dynamic"


class Encoding(Enum):
	gzip = "gzip"
	deflate = "deflate"
	br = "br"

	@property
	def max_level(self) -> int:
		match self:
			case Encoding.gzip | Encoding.deflate:
				return 9
			case Encoding.br:
				return 11

	def level_config_key(self, resource_type: ResourceType) -> str:
		match self:
			case Encoding.gzip:
				encoding_name = "GZIP"
			case Encoding.deflate:
				encoding_name = "DEFLATE"
			case Encoding.br:
				encoding_name = "BROTLI"
		return f"SQUEEZE_LEVEL_{encoding_name}_{resource_type.name.upper()}"


class Minification(Enum):
	js = "js"
	css = "css"
	html = "html"

	@property
	def enable_config_key(self) -> str:
		return f"SQUEEZE_MINIFY_{self.name.upper()}"

	@classmethod
	def for_mimetype(cls, mimetype: str | None) -> Minification | None:
		if mimetype is None:
			return None
		# Media types are case-insensitive, and werkzeug keeps the case of the Content-Type header
		match mimetype.lower():
			case "text/html":
				return cls.html
			case "text/css":
				return cls.css
			case "text/javascript" | "application/javascript" | "application/x-javascript":
				return cls.js
			case _:
				return None


@dataclass(frozen=True)
class Compression:
	encoding: Encoding
	level: int


@dataclass(frozen=True)
class SqueezePlan:
	"""What to do with one response body. At least one of compression or minification is set."""

	compression: Compression | None
	minification: Minification | None

	def __post_init__(self) -> None:
		if self.compression is None and self.minification is None:
			msg = "A SqueezePlan needs a compression, a minification, or both"
			raise ValueError(msg)

	@property
	def etag_suffix(self) -> str:
		"""Identifies the squeezed bytes, so each variant of a resource gets its own strong ETag."""
		parts: list[str] = []
		if self.minification is not None:
			parts.append(f"min{self.minification.value}")
		if self.compression is not None:
			parts.append(f"{self.compression.encoding.value}{self.compression.level}")
		return "-".join(parts)
