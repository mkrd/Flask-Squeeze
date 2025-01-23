import gzip
import zlib
from typing import Dict, Tuple, Union

import brotli
from flask import Flask, Response, request

from flask_squeeze.utils import add_breach_exploit_protection_header

from .debug import add_debug_header, ctx_add_benchmark_header
from .log import d_log, log
from .minifiers import minify_css, minify_html, minify_js
from .models import (
	Encoding,
	Minification,
	ResourceType,
	choose_encoding_from_headers_and_config,
	choose_minification_from_mimetype_and_config,
)


class Squeeze:
	__slots__ = "app", "cache"
	app: Flask

	cache: Dict[Tuple[str, str], bytes]
	""" (request.path, encoding) -> compressed bytes """

	def __init__(self, app: Union[Flask, None] = None) -> None:
		"""Initialize Flask-Squeeze with or without app."""
		self.cache = {}
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
		# Logging options
		app.config.setdefault("SQUEEZE_VERBOSE_LOGGING", False)
		app.config.setdefault("SQUEEZE_ADD_DEBUG_HEADERS", False)

		if (
			app.config["SQUEEZE_COMPRESS"]
			or app.config["SQUEEZE_MINIFY_JS"]
			or app.config["SQUEEZE_MINIFY_CSS"]
			or app.config["SQUEEZE_MINIFY_HTML"]
		):
			app.after_request(self.after_request)

	# Minification
	####################################################################################

	@d_log(level=2, with_args=[1])
	def execute_minify(
		self,
		response: Response,
		minify_choice: Union[Minification, None],
	) -> None:
		"""
		Dispatch minification to the correct function.
		Exit early if minification is not enabled for the repsonse mimetype.
		"""
		response.direct_passthrough = False
		data = response.get_data(as_text=True)

		log(3, f"Minifying {minify_choice} resource")

		with ctx_add_benchmark_header("X-Flask-Squeeze-Minify-Duration", response):
			if minify_choice == Minification.html:
				minified = minify_html(data)
			elif minify_choice == Minification.css:
				minified = minify_css(data)
			elif minify_choice == Minification.js:
				minified = minify_js(data)
			else:
				raise ValueError(f"Invalid minify choice {minify_choice} at {request.path}")
			minified = minified.encode("utf-8")

		log(3, f"Minify ratio: {len(data) / len(minified):.2f}x")
		response.set_data(minified)

	# Compression
	####################################################################################

	@d_log(level=2, with_args=[1, 2, 3])
	def execute_compress(
		self,
		response: Response,
		resource_type: ResourceType,
		encode_choice: Union[Encoding, None],
	) -> None:
		response.direct_passthrough = False
		data = response.get_data(as_text=False)

		options = {
			(Encoding.br, ResourceType.static): "SQUEEZE_LEVEL_BROTLI_STATIC",
			(Encoding.br, ResourceType.dynamic): "SQUEEZE_LEVEL_BROTLI_DYNAMIC",
			(Encoding.deflate, ResourceType.static): "SQUEEZE_LEVEL_DEFLATE_STATIC",
			(Encoding.deflate, ResourceType.dynamic): "SQUEEZE_LEVEL_DEFLATE_DYNAMIC",
			(Encoding.gzip, ResourceType.static): "SQUEEZE_LEVEL_GZIP_STATIC",
			(Encoding.gzip, ResourceType.dynamic): "SQUEEZE_LEVEL_GZIP_DYNAMIC",
		}

		if (option := options.get((encode_choice or Encoding.gzip, resource_type))) is None:
			raise ValueError(f"Invalid encoding choice {encode_choice} for {resource_type} resource at {request.path}")

		quality = self.app.config[option]

		log(3, f"Compressing resource with {encode_choice} encoding, and quality {quality}.")

		with ctx_add_benchmark_header("X-Flask-Squeeze-Compress-Duration", response):
			if encode_choice == Encoding.br:
				compressed_data = brotli.compress(data, quality=quality)
			elif encode_choice == Encoding.deflate:
				compressed_data = zlib.compress(data, level=quality)
			elif encode_choice == Encoding.gzip:
				compressed_data = gzip.compress(data, compresslevel=quality)
			else:
				raise ValueError(
					f"Invalid encoding choice {encode_choice} for {resource_type} resource at {request.path}"
				)

		log(3, (f"Compression ratio: {len(data) / len(compressed_data):.1f}x, used {encode_choice}"))

		response.set_data(compressed_data)

	# Helpers
	####################################################################################

	def recompute_headers(
		self,
		response: Response,
		original_content_length: int,
		encode_choice: Union[Encoding, None],
	) -> None:
		"""
		Set the Content-Length header if it has changed.
		Set the Content-Encoding header if compressed data is served.
		"""
		if response.direct_passthrough:
			return

		if isinstance(encode_choice, Encoding):
			response.headers["Content-Encoding"] = encode_choice.value
			vary = {x.strip() for x in response.headers.get("Vary", "").split(",")}
			vary.add("Accept-Encoding")
			vary.discard("")
			response.headers["Vary"] = ",".join(vary)

		if original_content_length != response.content_length:
			response.headers["Content-Length"] = response.content_length
			response.headers["X-Uncompressed-Content-Length"] = original_content_length

	# After request handler
	####################################################################################

	def run(
		self,
		response: Response,
		encode_choice: Union[Encoding, None],
		minify_choice: Union[Minification, None],
	) -> None:
		if "/static/" in request.path:
			# Serve from cache if possible
			encode_choice_str = encode_choice.value if encode_choice else "none"
			from_cache = self.cache.get((request.path, encode_choice_str))
			if from_cache is not None:
				log(2, "Found in cache. RETURN")
				response.direct_passthrough = False
				response.set_data(from_cache)
				response.headers["X-Flask-Squeeze-Cache"] = "HIT"
				return
			# Assert: not in cache
			if isinstance(minify_choice, Minification):
				self.execute_minify(response, minify_choice)
			if isinstance(encode_choice, Encoding):
				self.execute_compress(response, ResourceType.static, encode_choice)
			# Assert: At least one of minify or compress was run
			response.headers["X-Flask-Squeeze-Cache"] = "MISS"
			self.cache[(request.path, encode_choice_str)] = response.get_data(as_text=False)
		else:
			if isinstance(minify_choice, Minification):
				self.execute_minify(response, minify_choice)
			if isinstance(encode_choice, Encoding):
				self.execute_compress(response, ResourceType.dynamic, encode_choice)
				add_breach_exploit_protection_header(response)

	@d_log(level=0, with_args=[1])
	@add_debug_header("X-Flask-Squeeze-Total-Duration")
	def after_request(self, response: Response) -> Response:
		log(1, f"Enter after_request({response})")

		if response.status_code is None or response.content_length is None:
			log(1, "Response status code or content length is None. RETURN")
			return response

		if response.status_code < 200 or response.status_code >= 300:
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

		encode_choice = choose_encoding_from_headers_and_config(
			request.headers,
			self.app.config,
		)

		minify_choice = choose_minification_from_mimetype_and_config(
			response.mimetype,
			self.app.config,
		)

		if encode_choice is None and minify_choice is None:
			log(1, "No compression or minification requested. RETURN")
			return response

		original_content_length = response.content_length
		self.run(response, encode_choice, minify_choice)
		self.recompute_headers(response, original_content_length, encode_choice)
		log(1, f"Cached: {self.cache.keys()}")
		return response
