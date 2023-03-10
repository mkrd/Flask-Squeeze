from typing import Tuple, Dict, Union
import gzip
import time
import zlib
import secrets
import random

from flask import Flask, Response, request
from rjsmin import jsmin
from rcssmin import cssmin
import htmlmin
import brotli

from .logger import (
	d_log,
	log,
)
from .debugger import (
	ctx_add_debug_header,
	add_debug_header,
)
from .utils import (
	get_requested_encoding,
	get_requested_encoding_str,
	get_resource_type,
)



class Squeeze(object):
	cache: Dict[Tuple[str, str, bool], bytes]  # keys are (request.path, encoding, is_minified)
	app: Flask


	def __init__(self, app: Flask = None) -> None:
		""" Initialize Flask-Squeeze with or without app. """
		self.cache = {}
		self.app = app
		if app is not None:
			self.init_app(app)


	def init_app(self, app: Flask) -> None:
		""" Initialize Flask-Squeeze with app """
		self.app = app
		app.config.setdefault("COMPRESS_FLAG", True)
		app.config.setdefault("COMPRESS_MIN_SIZE", 500)

		app.config.setdefault("COMPRESS_LEVEL_GZIP_STATIC", 9)
		app.config.setdefault("COMPRESS_LEVEL_GZIP_DYNAMIC", 1)
		app.config.setdefault("COMPRESS_LEVEL_BROTLI_STATIC", 11)
		app.config.setdefault("COMPRESS_LEVEL_BROTLI_DYNAMIC", 1)
		app.config.setdefault("COMPRESS_LEVEL_DEFLATE_STATIC", 9)
		app.config.setdefault("COMPRESS_LEVEL_DEFLATE_DYNAMIC", 1)

		app.config.setdefault("COMPRESS_MINIFY_JS", True)
		app.config.setdefault("COMPRESS_MINIFY_CSS", True)
		app.config.setdefault("COMPRESS_MINIFY_HTML", True)

		app.config.setdefault("COMPRESS_VERBOSE_LOGGING", False)
		app.config.setdefault("COMPRESS_ADD_DEBUG_HEADERS", False)

		if app.config["COMPRESS_FLAG"]:
			app.after_request(self.after_request)

	# Cache
	####################################################################################

	@d_log(level=2, with_args=[1, 2, 3])
	def get_from_cache(self, request_path: str, encoding: str, is_minified: bool) -> Union[bytes, None]:
		file = request_path.replace("/static/", "")
		return self.cache.get((file, encoding, is_minified), None)


	@d_log(level=2, with_args=[1, 2, 3])
	def insert_to_cache(self, request_path: str, encoding: str, is_minified: bool, value: bytes) -> None:
		file = request_path.replace("/static/", "")
		self.cache[(file, encoding, is_minified)] = value



	# Minification
	####################################################################################



	def should_minify(self, response: Response) -> bool:
		""" Return True if the response should be minified. """
		resource_type = get_resource_type(response)
		return (
			(resource_type.is_html and self.app.config["COMPRESS_MINIFY_HTML"]) or
			(resource_type.is_css and self.app.config["COMPRESS_MINIFY_CSS"]) or
			(resource_type.is_js and self.app.config["COMPRESS_MINIFY_JS"])
		)



	@d_log(level=2, with_args=[1])
	def dispatch_minify(self, response: Response) -> bool:
		"""
			Dispatch minification to the correct function.
			Exit early if minification is not enabled for the repsonse mimetype.
		"""

		resource_type = get_resource_type(response)
		if not self.should_minify(response):
			return False

		response.direct_passthrough = False
		data = response.get_data(as_text=True)

		with ctx_add_debug_header("X-Flask-Squeeze-Minify-Duration", response):
			if resource_type.is_html:
				minified = htmlmin.main.minify(data)
			elif resource_type.is_css:
				minified = cssmin(data, keep_bang_comments=False)
			elif resource_type.is_js:
				minified = jsmin(data, keep_bang_comments=False)

		minified = minified.encode("utf-8")
		log(3, f"Minify ratio: {len(data) / len(minified):.2f}x")
		response.set_data(minified)

		return True


	# Compression
	####################################################################################


	def select_quality_from_config(self, encoding: str, resource_type: str) -> str:
		options = {
			("br", "static"):       "COMPRESS_LEVEL_BROTLI_STATIC",
			("br", "dynamic"):      "COMPRESS_LEVEL_BROTLI_DYNAMIC",
			("deflate", "static"):  "COMPRESS_LEVEL_DEFLATE_STATIC",
			("deflate", "dynamic"): "COMPRESS_LEVEL_DEFLATE_DYNAMIC",
			("gzip", "static"):     "COMPRESS_LEVEL_GZIP_STATIC",
			("gzip", "dynamic"):    "COMPRESS_LEVEL_GZIP_DYNAMIC",
		}
		return self.app.config[options[(encoding, resource_type)]]


	def should_compress(self, response: Response) -> bool:
		""" Return True if the response should be compressed. """
		requested_encoding = get_requested_encoding(request)
		return self.app.config["COMPRESS_FLAG"] and not requested_encoding.none



	@d_log(level=2, with_args=[1, 2, 3])
	def dispatch_compress(self, response: Response, encoding: str, resource_type: str) -> bool:
		requested_encoding = get_requested_encoding(request)
		if not self.should_compress(response):
			print("should not compress")
			return False

		response.direct_passthrough = False
		data = response.get_data(as_text=False)

		quality = self.select_quality_from_config(encoding, resource_type)
		log(3, f"Compressing {resource_type} resource with {encoding}, quality {quality}.")

		with ctx_add_debug_header("X-Flask-Squeeze-Compress-Duration", response):
			if requested_encoding.is_br:
				compressed_data = brotli.compress(data, quality=quality)
			elif requested_encoding.is_deflate:
				compressed_data = zlib.compress(data, level=quality)
			elif requested_encoding.is_gzip:
				compressed_data = gzip.compress(data, compresslevel=quality)

		compress_ratio = len(response.get_data(as_text=False)) / len(compressed_data)
		log(3, f"Compression ratio: {compress_ratio:.1f}x, used {encoding}")

		response.set_data(compressed_data)

		return True





	@d_log(level=1)
	def recompute_headers(self, response: Response, encoding: str, original_content_length: int) -> None:
		# If direct_passthrough is set, the response was not modified.
		if response.direct_passthrough:
			return

		if encoding != "none":
			response.headers["Content-Encoding"] = encoding
			vary = {x.strip() for x in response.headers.get("Vary", "").split(",")}
			vary.add("Accept-Encoding")
			vary.discard("")
			response.headers["Vary"] = ",".join(vary)

		if original_content_length != response.content_length:
			response.headers["Content-Length"] = response.content_length
			response.headers["X-Uncompressed-Content-Length"] = original_content_length



	@d_log(level=1)
	def run_for_dynamic_resource(self, response: Response, encoding: str) -> None:
		"""
			Compress a dynamic resource.
			- No caching is done.
		"""

		self.dispatch_minify(response)
		was_compressed = self.dispatch_compress(response, encoding, "dynamic")
		# Protect against BREACH attack
		if was_compressed:
			tx = 2 if int(time.time() ** 3.141592) % 2 else 1
			rand_str: str = secrets.token_urlsafe(random.randint(32 * tx, 128 * tx))
			response.headers["X-Breach-Exploit-Protection-Padding"] = rand_str



	@d_log(level=1)
	def run_for_static_resource(self, response: Response, encoding: str) -> None:
		"""
			Compress a static resource.
		"""

		should_minify = self.should_minify(response)

		if (from_cache := self.get_from_cache(request.path, encoding, should_minify)) is not None:
			log(1, "Found in cache. RETURN")
			response.direct_passthrough = False
			response.set_data(from_cache)
			response.headers["X-Flask-Squeeze-Cache"] = "HIT"
			return

		# Assert: not in cache

		minified = self.dispatch_minify(response)
		was_compressed = self.dispatch_compress(response, encoding, "static")

		if was_compressed or minified:
			response.headers["X-Flask-Squeeze-Cache"] = "MISS"
			data = response.get_data(as_text=False)
			self.insert_to_cache(request.path, encoding, minified, data)


	@d_log(level=0, with_args=[1])
	@add_debug_header("X-Flask-Squeeze-Total-Duration")
	def after_request(self, response: Response) -> Response:
		log(0, f"Enter after_request({response})")

		if response.status_code < 200 or response.status_code >= 300:
			log(1, "Response status code is not ok. RETURN")
			return response

		if response.content_length < self.app.config["COMPRESS_MIN_SIZE"]:
			log(1, "Response size is smaller than the defined minimum. RETURN")
			return response

		if "Content-Encoding" in response.headers:
			log(1, "Response already encoded. RETURN")
			return response

		# Assert: The response is ok, the size is above threshold, and the response is
		# not already encoded.

		encoding = get_requested_encoding_str(request)
		original_content_length = response.content_length

		if "/static/" not in request.path:
			log(1, "Dynamic resource. Compress and return.")
			self.run_for_dynamic_resource(response, encoding)
		else:
			log(1, "Static resource. Return from cache if already cached")
			self.run_for_static_resource(response, encoding)

		self.recompute_headers(response, encoding, original_content_length)

		log(0, f"cache keys: {self.cache.keys()}")
		return response
