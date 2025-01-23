import hashlib
from typing import Dict, Tuple, Union

from flask import Flask, Response, request

from flask_squeeze.utils import add_breach_exploit_protection_header

from .compress import add_compression_info_headers, compress
from .debug import add_debug_header
from .log import d_log, log
from .minify import add_minification_info_headers, minify
from .models import (
	Encoding,
	Minification,
	ResourceType,
	choose_encoding_from_headers_and_config,
	choose_minification_from_mimetype_and_config,
)


class Squeeze:
	__slots__ = "app", "cache_static"
	app: Flask

	cache_static: Dict[Tuple[str, str], tuple[str, bytes]]
	""" (request.path, encoding) -> (original file sha256 hash, compressed bytes) """

	def __init__(self, app: Union[Flask, None] = None) -> None:
		"""Initialize Flask-Squeeze with or without app."""
		self.cache_static = {}
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

	# Helpers
	####################################################################################

	def get_configured_quality(self, encode_choice: Encoding, resource_type: ResourceType) -> int:
		options = {
			(Encoding.br, ResourceType.static): "SQUEEZE_LEVEL_BROTLI_STATIC",
			(Encoding.br, ResourceType.dynamic): "SQUEEZE_LEVEL_BROTLI_DYNAMIC",
			(Encoding.deflate, ResourceType.static): "SQUEEZE_LEVEL_DEFLATE_STATIC",
			(Encoding.deflate, ResourceType.dynamic): "SQUEEZE_LEVEL_DEFLATE_DYNAMIC",
			(Encoding.gzip, ResourceType.static): "SQUEEZE_LEVEL_GZIP_STATIC",
			(Encoding.gzip, ResourceType.dynamic): "SQUEEZE_LEVEL_GZIP_DYNAMIC",
		}

		if not (option := options.get((encode_choice or Encoding.gzip, resource_type))):
			raise ValueError(f"Invalid encoding choice {encode_choice} for {resource_type} resource at {request.path}")

		return self.app.config[option]

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

	def run_dynamic(
		self,
		response: Response,
		encode_choice: Union[Encoding, None],
		minify_choice: Union[Minification, None],
	) -> None:
		if encode_choice is None and minify_choice is None:
			return  # Early exit if no compression or minification is requested

		response.direct_passthrough = False

		# Minification

		if minify_choice is not None:
			minification_result = minify(response.get_data(as_text=False), minify_choice)
			response.set_data(minification_result.data)
			add_minification_info_headers(response, minification_result)

		# Compression

		if encode_choice is not None:
			compression_result = compress(
				response.get_data(as_text=False),
				encode_choice,
				self.get_configured_quality(encode_choice, ResourceType.dynamic),
			)
			response.set_data(compression_result.data)
			add_compression_info_headers(response, compression_result)
			add_breach_exploit_protection_header(response)

	def run_static(
		self,
		response: Response,
		encode_choice: Union[Encoding, None],
		minify_choice: Union[Minification, None],
	) -> None:
		response.direct_passthrough = False  # Ensure we can read the data

		encode_choice_str = encode_choice.value if encode_choice else "none"
		cache_entry = self.cache_static.get((request.path, encode_choice_str))

		# Serve from cache

		if cache_entry is not None:
			original_sha256, compressed_data = cache_entry

			# Compare the original file hash with the current file hash

			current_data = response.get_data(as_text=False)
			current_sha256 = hashlib.sha256(current_data).hexdigest()

			if current_sha256 == original_sha256:
				log(2, "Found in cache. RETURN")
				response.set_data(compressed_data)
				response.headers["X-Flask-Squeeze-Cache"] = "HIT"
				return

			log(2, "File has changed.")

			if minify_choice is not None:
				minfication_result = minify(response.get_data(as_text=False), minify_choice)
				response.set_data(minfication_result.data)
				add_minification_info_headers(response, minfication_result)
			if encode_choice is not None:
				compression_result = compress(
					response.get_data(as_text=False),
					encode_choice,
					self.get_configured_quality(encode_choice, ResourceType.static),
				)
				response.set_data(compression_result.data)
				add_compression_info_headers(response, compression_result)

			# Assert: At least one of minify or compress was run

			response.headers["X-Flask-Squeeze-Cache"] = "MISS"
			data = response.get_data(as_text=False)

			self.cache_static[(request.path, encode_choice_str)] = (current_sha256, data)
			return

		# Not in cache, compress and minify

		original_data = response.get_data(as_text=False)
		original_sha256 = hashlib.sha256(original_data).hexdigest()

		if minify_choice is not None:
			minification_result = minify(original_data, minify_choice)
			response.set_data(minification_result.data)
			add_minification_info_headers(response, minification_result)
		if encode_choice is not None:
			compression_result = compress(
				response.get_data(as_text=False),
				encode_choice,
				self.get_configured_quality(encode_choice, ResourceType.static),
			)
			response.set_data(compression_result.data)
			add_compression_info_headers(response, compression_result)

		# Assert: At least one of minify or compress was run

		compressed_data = response.get_data(as_text=False)
		self.cache_static[(request.path, encode_choice_str)] = (original_sha256, compressed_data)
		response.headers["X-Flask-Squeeze-Cache"] = "MISS"

	def run(
		self,
		response: Response,
		encode_choice: Union[Encoding, None],
		minify_choice: Union[Minification, None],
	) -> None:
		if request.path.startswith("/static/"):
			self.run_static(response, encode_choice, minify_choice)
		else:
			self.run_dynamic(response, encode_choice, minify_choice)

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
		log(1, f"Static cache: {self.cache_static.keys()}")
		return response
