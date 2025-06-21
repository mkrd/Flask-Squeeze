from __future__ import annotations

import hashlib
from pathlib import Path

from flask import Flask, Response, request

from .cache import Cache, CacheKey
from .compress import CompressionInfo, compress
from .log import d_log, log
from .minify import MinificationInfo, minify
from .models import Encoding, Minification, ResourceType
from .utils import add_breach_exploit_protection_header, update_response_headers


class Squeeze:
	__slots__ = "app", "cache_static"
	app: Flask

	cache_static: Cache
	""" (request.path, encoding) -> (original file sha256 hash, compressed bytes) """

	def __init__(self, app: Flask | None = None) -> None:
		"""Initialize Flask-Squeeze with or without app."""
		if app is None:
			return
		self.app = app
		self.init_app(app)

	def init_app(self, app: Flask) -> None:
		"""Initialize Flask-Squeeze with app"""
		self.app = app
		# Compression options
		app.config.setdefault("SQUEEZE_COMPRESS", True)
		app.config.setdefault("SQUEEZE_MIN_SIZE", 500)
		# Compression levels
		app.config.setdefault("SQUEEZE_LEVEL_GZIP_STATIC", 9)
		app.config.setdefault("SQUEEZE_LEVEL_GZIP_DYNAMIC", 1)
		app.config.setdefault("SQUEEZE_LEVEL_BROTLI_STATIC", 11)
		app.config.setdefault("SQUEEZE_LEVEL_BROTLI_DYNAMIC", 1)
		app.config.setdefault("SQUEEZE_LEVEL_DEFLATE_STATIC", 9)
		app.config.setdefault("SQUEEZE_LEVEL_DEFLATE_DYNAMIC", 1)
		# Minification options
		app.config.setdefault("SQUEEZE_MINIFY_JS", True)
		app.config.setdefault("SQUEEZE_MINIFY_CSS", True)
		app.config.setdefault("SQUEEZE_MINIFY_HTML", True)
		# Caching options
		app.config.setdefault("SQUEEZE_CACHE_DIR", None)
		# Logging options
		app.config.setdefault("SQUEEZE_VERBOSE_LOGGING", False)

		# Initialize cache

		cache_dir = app.config.get("SQUEEZE_CACHE_DIR")
		self.cache_static = Cache(
			data={},
			cache_dir=Path(cache_dir) if cache_dir else None,
		)

		# Initialize after_request hook

		if (
			app.config["SQUEEZE_COMPRESS"]
			or app.config["SQUEEZE_MINIFY_JS"]
			or app.config["SQUEEZE_MINIFY_CSS"]
			or app.config["SQUEEZE_MINIFY_HTML"]
		):
			app.after_request(self.after_request)

	####################################################################################
	#### MARK: Utils

	def get_configured_quality(self, encode_choice: Encoding, resource_type: ResourceType) -> int:
		options = {
			(Encoding.br, ResourceType.static): "SQUEEZE_LEVEL_BROTLI_STATIC",
			(Encoding.br, ResourceType.dynamic): "SQUEEZE_LEVEL_BROTLI_DYNAMIC",
			(Encoding.deflate, ResourceType.static): "SQUEEZE_LEVEL_DEFLATE_STATIC",
			(Encoding.deflate, ResourceType.dynamic): "SQUEEZE_LEVEL_DEFLATE_DYNAMIC",
			(Encoding.gzip, ResourceType.static): "SQUEEZE_LEVEL_GZIP_STATIC",
			(Encoding.gzip, ResourceType.dynamic): "SQUEEZE_LEVEL_GZIP_DYNAMIC",
		}

		option = options[(encode_choice, resource_type)]

		return self.app.config[option]

	####################################################################################
	#### MARK: Dynamic

	def run_dynamic(
		self,
		response: Response,
		encode_choice: Encoding | None,
		minify_choice: Minification | None,
	) -> None:
		assert encode_choice or minify_choice

		data, minification_info, compression_info = self.squeeze(
			response.get_data(as_text=False),
			ResourceType.dynamic,
			minify_choice,
			encode_choice,
		)

		response.set_data(data)

		if minification_info:
			response.headers.update(minification_info.headers)

		if compression_info:
			response.headers.update(compression_info.headers)
			add_breach_exploit_protection_header(response)

	####################################################################################
	#### MARK: Static

	def run_static(
		self,
		response: Response,
		encode_choice: Encoding | None,
		minify_choice: Minification | None,
	) -> None:
		"""
		If the hash of the current response matches the hash of the cached response,
		return the cached response. Otherwise, compress and minify the response and
		cache the compressed response.
		"""
		assert encode_choice or minify_choice

		data = response.get_data(as_text=False)
		data_hash = hashlib.sha256(data).hexdigest()

		cache_key = CacheKey(request.path, encode_choice)
		cached = self.cache_static.get(cache_key)

		if cached is not None and data_hash == cached.original_hash:
			log(2, "Found in cache, hashes match. RETURN")
			response.set_data(cached.data)
			response.headers["X-Flask-Squeeze-Cache"] = "HIT"
			return

		# Not in cache, compress and minify

		log(2, "Not in cache or hashes don't match. Squeeze and cache.")
		data, minification_info, compression_info = self.squeeze(
			data,
			ResourceType.static,
			minify_choice,
			encode_choice,
		)

		response.set_data(data)

		if minification_info:
			response.headers.update(minification_info.headers)

		if compression_info:
			response.headers.update(compression_info.headers)

		response.headers["X-Flask-Squeeze-Cache"] = "MISS"

		# Cache the compressed data, with the dash of the original data
		self.cache_static.set(cache_key, data_hash, data)

	def squeeze(
		self,
		data: bytes,
		resource_type: ResourceType,
		minify_choice: Minification | None,
		encode_choice: Encoding | None,
	) -> tuple[bytes, MinificationInfo | None, CompressionInfo | None]:
		assert encode_choice or minify_choice

		minification_info = None
		if minify_choice is not None:
			data, minification_info = minify(data, minify_choice)

		compression_info = None
		if encode_choice is not None:
			data, compression_info = compress(
				data,
				encode_choice,
				self.get_configured_quality(encode_choice, resource_type),
			)

		return data, minification_info, compression_info

	####################################################################################
	#### MARK: After Request

	@d_log(level=0, with_args=[1])
	def after_request(self, response: Response) -> Response:
		log(1, f"Enter after_request({response})")

		if response.status_code is None or response.content_length is None:
			log(1, "Response status code or content length is None. RETURN")
			return response

		if response.status_code not in range(200, 300):
			log(1, "Response status code is not ok. RETURN")
			return response

		if response.content_length < self.app.config["SQUEEZE_MIN_SIZE"]:
			log(1, "Response size is smaller than the defined minimum. RETURN")
			return response

		if "Content-Encoding" in response.headers:
			log(1, "Response already encoded. RETURN")
			return response

		# Assert: The response is ok, the size is above threshold, and the response is
		# not already encoded.

		encode_choice = Encoding.get_from_headers_and_config(
			request.headers,
			self.app.config,
		)

		minify_choice = Minification.get_from_mimetype_and_config(
			response.mimetype,
			self.app.config,
		)

		if encode_choice is None and minify_choice is None:
			log(1, "No compression or minification requested. RETURN")
			return response

		# At least one of minify or compress is requested

		response.direct_passthrough = False  # In both cases, we need to read the data

		if request.path.startswith("/static/"):
			self.run_static(response, encode_choice, minify_choice)
		else:
			self.run_dynamic(response, encode_choice, minify_choice)

		update_response_headers(response, encode_choice)

		log(1, f"Static cache: {self.cache_static.data.keys()}")
		return response
