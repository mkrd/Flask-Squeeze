from flask import Flask, Response, Request, current_app, request
import gzip
import brotli
from rjsmin import jsmin
from rcssmin import cssmin
import functools
import time



def format_log(
	message: str,
	level: int,
	request: Request,
	color_code: int,
) -> str:
	log = f"Flask-Squeeze: {request.method} {request.path} -> {4 * level * ' '}{message}"
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

			t1 = time.perf_counter()
			res = method(*args, **kwargs)
			t2 = time.perf_counter()

			ms = f"{((t2 - t1) * 1000):.1f}ms"
			arglist = [f"{a}" for i, a in enumerate(args) if i in self.with_args]
			kwarglist = [f"{k}={a}" for k, a in kwargs.items() if k in self.with_kwargs]
			log = f"{method.__name__}({', '.join(arglist + kwarglist)}) - {ms}"
			print(format_log(log, self.level, request, 96))

			return res
		return wrapper



class Squeeze(object):


	def log(self, level: int, s: str) -> None:
		if self.app.config["COMPRESS_VERBOSE_LOGGING"]:
			print(format_log(s, level, request, 92))


	def __init__(self, app: Flask = None):
		""" Initialize Flask-Squeeze with or without app. """
		self.cache = {}
		self.app = app
		if app is not None:
			self.init_app(app)


	def init_app(self, app: Flask) -> None:
		""" Initialize Flask-Squeeze with app """
		self.app = app
		app.config.setdefault("COMPRESS_MIN_SIZE", 500)
		app.config.setdefault("COMPRESS_FLAG", True)
		app.config.setdefault("COMPRESS_LEVEL_GZIP_STATIC", 9)
		app.config.setdefault("COMPRESS_LEVEL_GZIP_DYNAMIC", 1)
		app.config.setdefault("COMPRESS_LEVEL_BROTLI_STATIC", 11)
		app.config.setdefault("COMPRESS_LEVEL_BROTLI_DYNAMIC", 1)
		app.config.setdefault("COMPRESS_MINIFY_JS", True)
		app.config.setdefault("COMPRESS_MINIFY_CSS", True)
		app.config.setdefault("COMPRESS_VERBOSE_LOGGING", False)
		if app.config["COMPRESS_FLAG"]:
			app.after_request(self.after_request)


	@logger(level=1, with_args=[1])
	def get_from_cache(self, key):
		return self.cache[key]


	@logger(level=1, with_args=[1])
	def insert_to_cache(self, key, value):
		self.cache[key] = value


	@logger(level=1, with_args=[1, 2, 3])
	def compress(self, response: Response, compression_method: str, compression_type: str) -> bytes:
		"""
			For a given response, return its contents
			as a brotli compressed bytes object.
			quality can be 0-11 for brotli, 0-9 for gzip.
		"""
		if response.mimetype in ["application/javascript", "application/json"] and self.app.config["COMPRESS_MINIFY_JS"]:
			data = response.get_data(as_text=True)
			data = jsmin(data, keep_bang_comments=False).encode("utf-8")
		elif response.mimetype == "text/css" and self.app.config["COMPRESS_MINIFY_CSS"]:
			data = response.get_data(as_text=True)
			data = cssmin(data, keep_bang_comments=False).encode("utf-8")
		else:
			data = response.get_data(as_text=False)

		if compression_method == "br":
			if compression_type == "static":
				quality = self.app.config["COMPRESS_LEVEL_BROTLI_STATIC"]
			else:
				quality = self.app.config["COMPRESS_LEVEL_BROTLI_DYNAMIC"]
			self.log(2, f"Compressing with brotli, quality {quality}.")
			compressed = brotli.compress(data, quality=quality)
		elif compression_method == "gzip":
			if compression_type == "static":
				quality = self.app.config["COMPRESS_LEVEL_GZIP_STATIC"]
			else:
				quality = self.app.config["COMPRESS_LEVEL_GZIP_DYNAMIC"]
			self.log(2, f"Compressing with gzip, quality {quality}.")
			compressed = gzip.compress(data, compresslevel=quality)
		else:
			raise ValueError(f"Unsupported compression type {compression_method}. Must be 'br' or 'gzip'.")
		self.log(2, f"Compression ratio: {len(response.data) / len(compressed):.1f}x")
		return compressed


	@logger(level=1)
	def recompute_headers(self, response: Response, compression_type: str):
		response.headers["Content-Encoding"] = compression_type
		response.headers["Content-Length"] = response.content_length
		# Vary defines which headers have to change for the cached version to become invalid
		vary = {s.strip() for s in response.headers.get("Vary", "").split(",")}
		vary.update(["Content-Encoding", "Content-Length"])
		vary.remove("")
		response.headers["Vary"] = ",".join(vary)


	@logger(level=0, with_args=[1])
	def after_request(self, response: Response):
		self.log(0, f"Enter after_request({response})")

		accepted_encodings = request.headers.get("Accept-Encoding", "").lower()
		compression_type = None
		if "gzip" in accepted_encodings:
			compression_type = "gzip"
		if "br" in accepted_encodings:
			compression_type = "br"

		if compression_type is None:
			self.log(1, "Requester does not accept Brotli or GZIP encoded responses. RETURN")
			return response
		if response.status_code < 200 or response.status_code >= 300:
			self.log(1, "Response status code is not ok. RETURN")
			return response
		if response.content_length < self.app.config["COMPRESS_MIN_SIZE"]:
			self.log(1, "Response size is smaller than the defined minimum. RETURN")
			return response
		if "Content-Encoding" in response.headers:
			self.log(1, "Response already encoded. RETURN")
			return response

		# Assert: The requester accepts gzip or br, the response is ok, the response
		# size is above threshold, and the response is not already encoded

		# Stop direct passthrough  and set custtom headers
		response.direct_passthrough = False
		response.headers["X-Uncompressed-Content-Length"] = response.content_length

		# Compress the response, cache if static
		if "/static/" in request.path:
			self.log(1, "Static resource. Return from cache if already cached")
			if request.path not in self.cache:
				compressed = self.compress(response, compression_type, "static")
				self.insert_to_cache(request.path, compressed)
			response.data = self.get_from_cache(request.path)
		else:
			self.log(1, f"Dynamic resource. Compress using {compression_type} and return without caching")
			response.data = self.compress(response, compression_type, "dynamic")

		self.recompute_headers(response, compression_type)
		return response
