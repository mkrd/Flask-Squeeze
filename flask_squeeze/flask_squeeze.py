from __future__ import annotations

import hashlib

from flask import Flask, Response, request

from flask_squeeze.utils import add_breach_exploit_protection_header, update_response_headers

from .compress import compress, update_response_with_compressed_data
from .log import d_log, log
from .minify import minify, update_response_with_minified_data
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

	cache_static: dict[tuple[str, str], tuple[str, bytes]]
	""" (request.path, encoding) -> (original file sha256 hash, compressed bytes) """

	def __init__(self, app: Flask | None = None) -> None:
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

		response.direct_passthrough = False

		# Minification

		if minify_choice is not None:
			minification_result = minify(response.get_data(as_text=False), minify_choice)
			update_response_with_minified_data(response, minification_result)

		# Compression

		if encode_choice is not None:
			compression_result = compress(
				response.get_data(as_text=False),
				encode_choice,
				self.get_configured_quality(encode_choice, ResourceType.dynamic),
			)
			update_response_with_compressed_data(response, compression_result)
			add_breach_exploit_protection_header(response)

	####################################################################################
	#### MARK: Static

	def run_static(
		self,
		response: Response,
		encode_choice: Encoding | None,
		minify_choice: Minification | None,
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
				log(2, "Found in cache, hashes match. RETURN")
				response.set_data(compressed_data)
				response.headers["X-Flask-Squeeze-Cache"] = "HIT"
				return

			log(2, "File has changed.")

			if minify_choice is not None:
				minfication_result = minify(current_data, minify_choice)
				update_response_with_minified_data(response, minfication_result)
				current_data = minfication_result.data
			if encode_choice is not None:
				compression_result = compress(
					current_data,
					encode_choice,
					self.get_configured_quality(encode_choice, ResourceType.static),
				)
				update_response_with_compressed_data(response, compression_result)
				current_data = compression_result.data

			# Assert: At least one of minify or compress was run

			response.headers["X-Flask-Squeeze-Cache"] = "MISS"
			self.cache_static[(request.path, encode_choice_str)] = (current_sha256, current_data)

		# Not in cache, compress and minify

		else:
			original_data = response.get_data(as_text=False)
			original_sha256 = hashlib.sha256(original_data).hexdigest()

			if minify_choice is not None:
				minification_result = minify(original_data, minify_choice)
				update_response_with_minified_data(response, minification_result)
			if encode_choice is not None:
				compression_result = compress(
					response.get_data(as_text=False),
					encode_choice,
					self.get_configured_quality(encode_choice, ResourceType.static),
				)
				update_response_with_compressed_data(response, compression_result)

			# Assert: At least one of minify or compress was run

			compressed_data = response.get_data(as_text=False)
			self.cache_static[(request.path, encode_choice_str)] = (original_sha256, compressed_data)
			response.headers["X-Flask-Squeeze-Cache"] = "MISS"

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

		# At least one of minify or compress is requested

		original_content_length = response.content_length

		if request.path.startswith("/static/"):
			self.run_static(response, encode_choice, minify_choice)
		else:
			self.run_dynamic(response, encode_choice, minify_choice)

		update_response_headers(response, original_content_length, encode_choice)
		log(1, f"Static cache: {self.cache_static.keys()}")
		return response
