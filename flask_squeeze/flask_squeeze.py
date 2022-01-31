from flask import current_app, request
import brotli
import gzip
from rjsmin import jsmin
from rcssmin import cssmin
import functools
import time



def colored_str_by_color_code(s, color_code):
	res = "\033["
	res += f"{color_code}m{s}"
	res += "\033[0m"
	return res



class logger:
	"""
		decorator for logging.
		level: indent level
		with_args: list of indices of args that should apppear in the log
		with_kwargs: list of kwarg names that should appear in the log
	"""


	def __init__(self, level=0, with_args=[], with_kwargs=[]):
		self.level = level
		self.with_args = with_args
		self.with_kwargs = with_kwargs


	def __call__(self, method):
		@functools.wraps(method)
		def wrapper(*args, **kwargs):
			if not current_app.config["COMPRESS_VERBOSE_LOGGING"]:
				return method(*args, **kwargs)

			t1 = time.time()
			res = method(*args, **kwargs)
			t2 = time.time()

			ms = f"{((t2 - t1) * 1000):.1f}ms"
			log = f"Flask-Squeeze: {request.path} - {self.level * '    '}{method.__name__}"

			arglist = [f"{a}" for i, a in enumerate(args) if i in self.with_args]
			kwarglist = [f"{k}={a}" for k, a in kwargs.items() if k in self.with_kwargs]
			log += "(" + ", ".join(arglist + kwarglist) + ")" + " - " + ms

			print(colored_str_by_color_code(log, 96))
			return res
		return wrapper



class Squeeze(object):


	def log(self, level, s):
		if self.app.config["COMPRESS_VERBOSE_LOGGING"]:
			tabs = level * "    "
			log = colored_str_by_color_code("Flask-Squeeze: " + request.path + " - " + tabs + s, 96)
			print(log)


	def __init__(self, app=None):
		""" Initialize Flask-Squeeze with or without app. """
		self.cache = {}
		self.app = app
		if app is not None:
			self.init_app(app)


	def init_app(self, app):
		""" Initialize Flask-Squeeze with app """
		self.app = app
		app.config.setdefault("COMPRESS_MIN_SIZE", 500)
		app.config.setdefault("COMPRESS_FLAG", True)
		app.config.setdefault("COMPRESS_LEVEL_STATIC", 9)
		app.config.setdefault("COMPRESS_LEVEL_DYNAMIC", 5)
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


	@logger(level=1, with_args=[1, 2], with_kwargs=["quality"])
	def compress(self, response, quality: int = 6) -> bytes:
		"""
			For a given response, return its contents
			as a brotli compressed bytes object.
			quality can be 0-11.
		"""
		if response.mimetype in ["application/javascript", "application/json"] and self.app.config["COMPRESS_MINIFY_JS"]:
			data = response.get_data(as_text=True)
			data = jsmin(data, keep_bang_comments=False).encode("utf-8")
		elif response.mimetype == "text/css" and self.app.config["COMPRESS_MINIFY_CSS"]:
			data = response.get_data(as_text=True)
			data = cssmin(data, keep_bang_comments=False).encode("utf-8")
		else:
			data = response.get_data()

		if self.compression_type == "br":
			compressed = brotli.compress(data, quality=quality)
		elif self.compression_type == "gzip":
			compressed = gzip.compress(data, compresslevel=quality)
		self.log(2, f"Compression ratio: {len(response.data) / len(compressed):.1f}x")
		return compressed


	@logger(level=1)
	def recompute_headers(self, response):

		response.headers["Content-Encoding"] = self.compression_type
		response.headers["Content-Length"] = response.content_length
		# Vary defines which headers have to change for the cached version to become invalid
		vary = set([s.strip() for s in response.headers.get("Vary", "").split(",")])
		vary.update(["Content-Encoding", "Content-Length"])
		vary.remove("")
		response.headers["Vary"] = ",".join(vary)


	@logger(level=0, with_args=[1])
	def after_request(self, response):
		self.log(0, f"after_request called with response: {response}")

		# Exit if status code is not ok
		if response.status_code < 200 or response.status_code >= 300:
			self.log(1, "Response status code is not ok. RETURN")
			return response

		# Exit if response size is below threshold
		if response.content_length < self.app.config["COMPRESS_MIN_SIZE"]:
			self.log(1, "Response size is smaller than the defined minimum. RETURN")
			return response

		# Exit if response already has a content encoding
		if "Content-Encoding" in response.headers:
			self.log(1, "Response already encoded. RETURN")
			return response

		accepted_encodings = request.headers.get("Accept-Encoding", "").lower()
		accept_br = "br" in accepted_encodings
		accept_gzip = "gzip" in accepted_encodings

		# Exit if neither gzip nor br are accepted
		if not accept_br and not accept_gzip:
			self.log(1, "Requester does not accept Brotli or GZIP encoded responses. RETURN")
			return response

		# br of gzip or both are supported
		self.compression_type = "br" if accept_br else "gzip"

		# Stop direct passthrough  and set custtom headers
		response.direct_passthrough = False
		response.headers["X-Uncompressed-Content-Length"] = response.content_length

		# Compress the response, cache if static
		if "/static/" in request.path:
			self.log(1, "Static resource. Return from cache if already cached")
			if request.path not in self.cache:
				compressed = self.compress(response, quality=self.app.config["COMPRESS_LEVEL_STATIC"])
				self.insert_to_cache(request.path, compressed)
			response.data = self.get_from_cache(request.path)
		else:
			self.log(1, "Dynamic resource. Compress and return without caching")
			compressed = self.compress(response, self.app.config["COMPRESS_LEVEL_DYNAMIC"])
			response.data = compressed

		self.recompute_headers(response)
		return response
