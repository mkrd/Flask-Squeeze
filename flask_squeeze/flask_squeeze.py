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

from .cache import (
	Cache,
)

from .logging import (
	d_log,
	log,
)

from .debugging import (
	ctx_add_debug_header,
	add_debug_header,
)

from .utils import (
	RequestedEncoding,
	ResourceType,
)



class Squeeze(object):
	cache: Cache
	app: Flask

	requested_encoding: RequestedEncoding
	response_resource_type: ResourceType


	def __init__(self, app: Flask = None) -> None:
		""" Initialize Flask-Squeeze with or without app. """
		self.cache = Cache()
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
			app.before_request(self.before_request)


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

		log(3, f"Minifying {self.response_resource_type.value} resource")

		with ctx_add_debug_header("X-Flask-Squeeze-Minify-Duration", response):
			if self.response_resource_type.is_html:
				minified = htmlmin.main.minify(data)
			elif self.response_resource_type.is_css:
				minified = cssmin(data, keep_bang_comments=False)
			elif self.response_resource_type.is_js:
				minified = jsmin(data, keep_bang_comments=False)
			minified = minified.encode("utf-8")

		log(3, f"Minify ratio: {len(data) / len(minified):.2f}x")
		response.set_data(minified)


	# Compression
	####################################################################################


	def select_quality_from_config(self) -> str:
		option = (self.requested_encoding.value, "static" if self.static_resource else "dynamic")
		options = {
			("br", "static"):       "COMPRESS_LEVEL_BROTLI_STATIC",
			("br", "dynamic"):      "COMPRESS_LEVEL_BROTLI_DYNAMIC",
			("deflate", "static"):  "COMPRESS_LEVEL_DEFLATE_STATIC",
			("deflate", "dynamic"): "COMPRESS_LEVEL_DEFLATE_DYNAMIC",
			("gzip", "static"):     "COMPRESS_LEVEL_GZIP_STATIC",
			("gzip", "dynamic"):    "COMPRESS_LEVEL_GZIP_DYNAMIC",
		}
		return self.app.config[options[option]]



	@d_log(level=2, with_args=[1, 2, 3])
	def execute_compress(self, response: Response) -> None:
		response.direct_passthrough = False
		data = response.get_data(as_text=False)
		quality = self.select_quality_from_config()

		log(3, (
			f"Compressing {self.response_resource_type.value} resource with "
			f"{self.requested_encoding.value}, and quality {quality}."
		))

		with ctx_add_debug_header("X-Flask-Squeeze-Compress-Duration", response):
			if self.requested_encoding.is_br:
				compressed_data = brotli.compress(data, quality=quality)
			elif self.requested_encoding.is_deflate:
				compressed_data = zlib.compress(data, level=quality)
			elif self.requested_encoding.is_gzip:
				compressed_data = gzip.compress(data, compresslevel=quality)

		log(3, (
			f"Compression ratio: { len(data) / len(compressed_data):.1f}x, "
			f"used {self.requested_encoding.value}"
		))

		response.set_data(compressed_data)



	@d_log(level=1)
	def run_for_dynamic_resource(self, response: Response) -> None:
		"""
			Compress a dynamic resource.
			- No caching is done.
		"""

		if self.response_resource_type.should_minify:
			self.execute_minify(response)
		if should_compress := self.requested_encoding.should_compress:
			self.execute_compress(response)
		# Protect against BREACH attack
		if should_compress:
			tx = 2 if int(time.time() ** 3.141592) % 2 else 1
			rand_str: str = secrets.token_urlsafe(random.randint(32 * tx, 128 * tx))
			response.headers["X-Breach-Exploit-Protection-Padding"] = rand_str



	@d_log(level=1)
	def run_for_static_resource(self,
		response: Response,
	) -> None:
		"""
			Compress a static resource.
		"""

		should_compress = self.requested_encoding.should_compress
		should_minify = self.response_resource_type.should_minify
		encoding = self.requested_encoding.value

		from_cache = self.cache.get(request.path, encoding, should_minify)
		if from_cache is not None:
			log(1, "Found in cache. RETURN")
			response.direct_passthrough = False
			response.set_data(from_cache)
			response.headers["X-Flask-Squeeze-Cache"] = "HIT"
			return

		# Assert: not in cache

		if should_minify:
			self.execute_minify(response)
		if should_compress:
			self.execute_compress(response)

		# If compression or minification was done, insert into cache
		if should_compress or should_minify:
			response.headers["X-Flask-Squeeze-Cache"] = "MISS"
			data = response.get_data(as_text=False)
			self.cache.insert(request.path, encoding, should_minify, data)



	@d_log(level=1)
	def recompute_headers(self, response: Response, original_content_length: int) -> None:
		# If direct_passthrough is set, the response was not modified.
		if response.direct_passthrough:
			return

		if not self.requested_encoding.none:
			response.headers["Content-Encoding"] = self.requested_encoding.value
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

		self.requested_encoding = RequestedEncoding(request)
		self.response_resource_type = ResourceType(response)

		if not (self.requested_encoding.should_compress
			or self.response_resource_type.should_minify
		):
			log(1, "No compression or minification requested. RETURN")
			return response

		original_content_length = response.content_length

		if "/static/" not in request.path:
			log(1, "Dynamic resource. Compress and return.")
			self.static_resource = False
			self.run_for_dynamic_resource(response)
		else:
			log(1, "Static resource. Return from cache if already cached")
			self.static_resource = True
			self.run_for_static_resource(response)

		self.recompute_headers(response, original_content_length)

		log(1, f"cache {self.cache}")

		return response
