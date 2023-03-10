from typing import Tuple, Dict, Union
import gzip
import time
import functools
import zlib
import secrets
import random

from flask import Flask, Response, Request, current_app, request
import brotli
from rjsmin import jsmin
from rcssmin import cssmin
import htmlmin



def format_log(
	message: str,
	level: int,
	request: Request,
	color_code: int,
) -> str:
	log = f"Flask-Squeeze: {request.method} {request.path} | {2 * level * ' '}{message}"
	# ANSI escape code for color
	res = "\033["
	res += f"{color_code}m{log}"
	res += "\033[0m"
	return res



class logger:
	"""
		decorator for logging.
		level: indent level
		with_args: list of indices of args that should apppear in the log
		with_kwargs: list of kwarg names that should appear in the log
	"""


	def __init__(self, level=0, with_args=None, with_kwargs=None):
		self.level = level
		self.with_args = with_args if with_args is not None else []
		self.with_kwargs = with_kwargs if with_kwargs is not None else []


	def __call__(self, method):
		@functools.wraps(method)
		def wrapper(*args, **kwargs):
			if not current_app.config["COMPRESS_VERBOSE_LOGGING"]:
				return method(*args, **kwargs)

			chosen_args = [f"{a}" for i, a in enumerate(args) if i in self.with_args]
			chosen_kwargs = [f"{k}={a}" for k, a in kwargs.items() if k in self.with_kwargs]
			begin_log = f"{method.__name__}({', '.join(chosen_args + chosen_kwargs)}) {{"
			print(format_log(begin_log, self.level, request, 96))

			t1 = time.perf_counter()
			res = method(*args, **kwargs)
			t2 = time.perf_counter()

			end_log = f"}} -> {((t2 - t1) * 1000):.2f}ms" + ("\n" if self.level == 0 else "")
			print(format_log(end_log, self.level, request, 96))

			return res
		return wrapper


def get_requested_encoding(request: Request) -> str:
	accepted_encodings = request.headers.get("Accept-Encoding", "").lower()
	if "br" in accepted_encodings:
		return "br"
	if "deflate" in accepted_encodings:
		return "deflate"
	if "gzip" in accepted_encodings:
		return "gzip"
	return "none"


def is_js(mimetype: str) -> bool:
	return mimetype.endswith("javascript") or mimetype.endswith("json")


def is_css(mimetype: str) -> bool:
	return mimetype.endswith("css")


def is_html(mimetype: str) -> bool:
	return mimetype.endswith("html")



class Squeeze(object):
	cache: Dict[Tuple[str, str, bool], bytes]  # keys are (request.path, encoding, is_minified)
	app: Flask


	def log(self, level: int, s: str) -> None:
		if self.app.config["COMPRESS_VERBOSE_LOGGING"]:
			print(format_log(s, level, request, 92))


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
		if app.config["COMPRESS_FLAG"]:
			app.after_request(self.after_request)


	@logger(level=2, with_args=[1, 2, 3])
	def get_from_cache(self, request_path: str, encoding: str, is_minified: bool) -> Union[bytes, None]:
		file = request_path.replace("/static/", "")
		return self.cache.get((file, encoding, is_minified), None)


	@logger(level=2, with_args=[1, 2, 3])
	def insert_to_cache(self, request_path: str, encoding: str, is_minified: bool, value: bytes) -> None:
		file = request_path.replace("/static/", "")
		self.cache[(file, encoding, is_minified)] = value



	def execute_minify(self, response: Response, file_type: str) -> None:
		response.direct_passthrough = False
		data = response.get_data(as_text=True)

		if file_type == "html":
			minified = htmlmin.main.minify(data)
		elif file_type == "css":
			minified = cssmin(data, keep_bang_comments=False)
		elif file_type == "js":
			minified = jsmin(data, keep_bang_comments=False)
		minified = minified.encode("utf-8")

		self.log(3, f"Minify ratio: {len(data) / len(minified):.2f}x")
		response.set_data(minified)


	@logger(level=2)
	def minify_if_js(self, response: Response) -> bool:
		if not self.app.config["COMPRESS_MINIFY_JS"]:
			self.log(2, "Minifying javascript is disabled. EXIT.")
			return False
		if not is_js(response.mimetype):
			self.log(3, f"MimeType is not js or json but {response.mimetype}. EXIT.")
			return False
		self.execute_minify(response, "js")
		return True


	@logger(level=2)
	def minify_if_css(self, response: Response) -> bool:
		if not self.app.config["COMPRESS_MINIFY_CSS"]:
			self.log(3, "Minifying css is disabled. EXIT.")
			return False
		if not is_css(response.mimetype):
			self.log(3, f"MimeType is not css but {response.mimetype}. EXIT.")
			return False
		self.execute_minify(response, "css")
		return True


	@logger(level=2)
	def minify_if_html(self, response: Response) -> bool:
		if not self.app.config["COMPRESS_MINIFY_HTML"]:
			self.log(3, "Minifying HTML is disabled. EXIT.")
			return False
		if not is_html(response.mimetype):
			self.log(3, f"MimeType is not HTML but {response.mimetype}. EXIT.")
			return False
		self.execute_minify(response, "html")
		return True


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



	@logger(level=2, with_args=[1, 2, 3])
	def compress(self, response: Response, encoding: str, resource_type: str) -> bool:
		"""
			For a given response, return its contents
			as a brotli compressed bytes object.
			quality can be 0-11 for brotli, 0-9 for gzip.
		"""

		if encoding not in ["br", "gzip", "deflate"]:
			return False

		response.direct_passthrough = False
		data = response.get_data(as_text=False)

		quality = self.select_quality_from_config(encoding, resource_type)
		self.log(3, f"Compressing {resource_type} resource with {encoding}, quality {quality}.")

		if encoding == "br":
			compressed_data = brotli.compress(data, quality=quality)
		elif encoding == "deflate":
			compressed_data = zlib.compress(data, level=quality)
		elif encoding == "gzip":
			compressed_data = gzip.compress(data, compresslevel=quality)

		compress_ratio = len(response.get_data(as_text=False)) / len(compressed_data)
		self.log(3, f"Compression ratio: {compress_ratio:.1f}x")

		response.set_data(compressed_data)
		return True


	@logger(level=1)
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



	@logger(level=1)
	def run_for_dynamic_resource(self, response: Response, encoding: str) -> None:
		"""
			Compress a dynamic resource.
			- No caching is done.
		"""

		self.minify_if_css(response)
		self.minify_if_js(response)
		self.minify_if_html(response)
		was_compressed = self.compress(response, encoding, "dynamic")
		# Protect against BREACH attack
		if was_compressed:
			tx = 2 if int(time.time() ** 3.141592) % 2 else 1
			rand_str: str = secrets.token_urlsafe(random.randint(32 * tx, 128 * tx))
			response.headers["X-Breach-Exploit-Protection-Padding"] = rand_str



	@logger(level=1)
	def run_for_static_resource(self, response: Response, encoding: str) -> None:
		"""
			Compress a static resource.
		"""

		m_css = is_css(response.mimetype) and self.app.config["COMPRESS_MINIFY_CSS"]
		m_js = is_js(response.mimetype) and self.app.config["COMPRESS_MINIFY_JS"]
		minify = m_css or m_js

		if (from_cache := self.get_from_cache(request.path, encoding, minify)) is not None:
			self.log(1, "Found in cache. RETURN")
			response.direct_passthrough = False
			response.set_data(from_cache)
			return

		# Assert: not in cache

		css_was_minified = self.minify_if_css(response)
		js_was_minified = self.minify_if_js(response)
		html_was_minified = self.minify_if_html(response)
		minified = css_was_minified or js_was_minified or html_was_minified
		was_compressed = self.compress(response, encoding, "static")

		if was_compressed or minified:
			data = response.get_data(as_text=False)
			self.insert_to_cache(request.path, encoding, minified, data)


	@logger(level=0, with_args=[1])
	def after_request(self, response: Response) -> Response:
		self.log(0, f"Enter after_request({response})")

		if response.status_code < 200 or response.status_code >= 300:
			self.log(1, "Response status code is not ok. RETURN")
			return response

		if response.content_length < self.app.config["COMPRESS_MIN_SIZE"]:
			self.log(1, "Response size is smaller than the defined minimum. RETURN")
			return response

		if "Content-Encoding" in response.headers:
			self.log(1, "Response already encoded. RETURN")
			return response

		# Assert: The response is ok, the size is above threshold, and the response is
		# not already encoded.

		encoding = get_requested_encoding(request)
		original_content_length = response.content_length

		if "/static/" not in request.path:
			self.log(1, "Dynamic resource. Compress and return.")
			self.run_for_dynamic_resource(response, encoding)
		else:
			self.log(1, "Static resource. Return from cache if already cached")
			self.run_for_static_resource(response, encoding)

		self.recompute_headers(response, encoding, original_content_length)

		self.log(0, f"cache keys: {self.cache.keys()}")
		return response
