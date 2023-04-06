import gzip
import random
import secrets
import time
import zlib
from typing import Union

import brotli
from flask import Flask, Response, request

from .cache import MemoryCache
from .debug import add_debug_header, ctx_add_debug_header
from .log import d_log, log
from .minifiers import minify_css, minify_html, minify_js
from .models import (
	Encoding,
	Minifcation,
	choose_encoding_from_headers_and_config,
	choose_minification_from_mimetype_and_config,
)


class Squeeze:

	__slots__ = "cache", "app", "encode_choice", "minify_choice", "resource_type"
	cache: MemoryCache
	app: Flask
	encode_choice: Union[Encoding, None]
	minify_choice: Union[Minifcation, None]
	resource_type: Union[str, None]


	def __init__(self, app: Flask = None) -> None:
		""" Initialize Flask-Squeeze with or without app. """
		self.cache = MemoryCache()
		self.app = app
		if app is not None:
			self.init_app(app)


	def init_app(self, app: Flask) -> None:
		""" Initialize Flask-Squeeze with app """
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

		if (app.config["SQUEEZE_COMPRESS"] or
			app.config["SQUEEZE_MINIFY_JS"] or
			app.config["SQUEEZE_MINIFY_CSS"] or
			app.config["SQUEEZE_MINIFY_HTML"]
		):
			app.after_request(self.after_request)


	# Minification
	####################################################################################


	@d_log(level=2, with_args=[1])
	def execute_minify(self, response: Response) -> None:
		"""
			Dispatch minification to the correct function.
			Exit early if minification is not enabled for the repsonse mimetype.
		"""
		response.direct_passthrough = False
		data = response.get_data(as_text=True)

		log(3, f"Minifying {self.minify_choice.value} resource")

		with ctx_add_debug_header("X-Flask-Squeeze-Minify-Duration", response):
			if self.minify_choice == Minifcation.html:
				minified = minify_html(data)
			elif self.minify_choice == Minifcation.css:
				minified = minify_css(data)
			elif self.minify_choice == Minifcation.js:
				minified = minify_js(data)
			minified = minified.encode("utf-8")

		log(3, f"Minify ratio: {len(data) / len(minified):.2f}x")
		response.set_data(minified)


	# Compression
	####################################################################################


	def select_quality_from_config(self) -> str:
		options = {
			(Encoding.br,      "static"):  "SQUEEZE_LEVEL_BROTLI_STATIC",
			(Encoding.br,      "dynamic"): "SQUEEZE_LEVEL_BROTLI_DYNAMIC",
			(Encoding.deflate, "static"):  "SQUEEZE_LEVEL_DEFLATE_STATIC",
			(Encoding.deflate, "dynamic"): "SQUEEZE_LEVEL_DEFLATE_DYNAMIC",
			(Encoding.gzip,    "static"):  "SQUEEZE_LEVEL_GZIP_STATIC",
			(Encoding.gzip,    "dynamic"): "SQUEEZE_LEVEL_GZIP_DYNAMIC",
		}
		return self.app.config[options[(self.encode_choice, self.resource_type)]]



	@d_log(level=2, with_args=[1, 2, 3])
	def execute_compress(self, response: Response) -> None:
		response.direct_passthrough = False
		data = response.get_data(as_text=False)
		quality = self.select_quality_from_config()

		log(3, (
			f"Compressing resource with {self.encode_choice.value} encoding",
			f", and quality {quality}."
		))

		with ctx_add_debug_header("X-Flask-Squeeze-Compress-Duration", response):
			if self.encode_choice == Encoding.br:
				compressed_data = brotli.compress(data, quality=quality)
			elif self.encode_choice == Encoding.deflate:
				compressed_data = zlib.compress(data, level=quality)
			elif self.encode_choice == Encoding.gzip:
				compressed_data = gzip.compress(data, compresslevel=quality)

		log(3, (
			f"Compression ratio: { len(data) / len(compressed_data):.1f}x, "
			f"used {self.encode_choice.value}"
		))

		response.set_data(compressed_data)



	@d_log(level=1)
	def run_for_dynamic_resource(self, response: Response) -> None:
		"""
			Compress a dynamic resource.
			- No caching is done.
		"""

		if self.minify_choice is not None:
			self.execute_minify(response)
		if self.encode_choice is not None:
			self.execute_compress(response)
		# Protect against BREACH attack
		if self.encode_choice:
			tx = 2 if int(time.time() ** 3.141592) % 2 else 1
			rand_str: str = secrets.token_urlsafe(random.randint(32 * tx, 128 * tx))
			response.headers["X-Breach-Exploit-Protection-Padding"] = rand_str



	@d_log(level=1)
	def run_for_static_resource(
		self,
		response: Response,
	) -> None:
		"""
			Compress a static resource.
		"""

		path = request.path
		from_cache = self.cache.get(path, self.encode_choice, self.minify_choice)
		if from_cache is not None:
			log(2, "Found in cache. RETURN")
			response.direct_passthrough = False
			response.set_data(from_cache)
			response.headers["X-Flask-Squeeze-Cache"] = "HIT"
			return

		# Assert: not in cache

		if self.minify_choice is not None:
			self.execute_minify(response)
		if self.encode_choice is not None:
			self.execute_compress(response)

		# If compression or minification was done, insert into cache
		if self.encode_choice or self.minify_choice:
			response.headers["X-Flask-Squeeze-Cache"] = "MISS"
			data = response.get_data(as_text=False)
			self.cache.insert(path, self.encode_choice, self.minify_choice, data)



	@d_log(level=1, with_args=[1, 2])
	def recompute_headers(
		self,
		response: Response,
		original_content_length: int
	) -> None:
		# If direct_passthrough is set, the response was not modified.
		if response.direct_passthrough:
			return

		if self.encode_choice:
			response.headers["Content-Encoding"] = self.encode_choice.value
			vary = {x.strip() for x in response.headers.get("Vary", "").split(",")}
			vary.add("Accept-Encoding")
			vary.discard("")
			response.headers["Vary"] = ",".join(vary)

		if original_content_length != response.content_length:
			response.headers["Content-Length"] = response.content_length
			response.headers["X-Uncompressed-Content-Length"] = original_content_length



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

		self.encode_choice = choose_encoding_from_headers_and_config(
			request.headers,
			self.app.config,
		)
		self.minify_choice = choose_minification_from_mimetype_and_config(
			response.mimetype,
			self.app.config,
		)

		if self.encode_choice is None and self.minify_choice is None:
			log(1, "No compression or minification requested. RETURN")
			return response

		original_content_length = response.content_length
		self.resource_type = "static" if "/static/" in request.path else "dynamic"

		if self.resource_type == "dynamic":
			log(1, "Dynamic resource.")
			self.run_for_dynamic_resource(response)
		else:
			log(1, "Static resource.")
			self.run_for_static_resource(response)

		self.recompute_headers(response, original_content_length)

		log(1, f"{self.cache}")

		return response
