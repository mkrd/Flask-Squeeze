from flask import current_app, request
import hashlib
import brotli
from rjsmin import jsmin
from rcssmin import cssmin
from termcolor import colored



VERBOSE_LOGGING = True


def log(s):
	if VERBOSE_LOGGING:
		text = colored(s, "cyan")
		print("Flask-Squeeze: " + text)


class Squeeze(object):

	def log(self, level, s):
		if self.app.config["COMPRESS_VERBOSE_LOGGING"]:
			text = colored(s, "cyan")
			tabs = level * "    "
			print("Flask-Squeeze: " + tabs + text)


	def __init__(self, app=None):
		self.cache = {}
		self.app = app
		if app is not None:
			self.init_app(app)


	def init_app(self, app):
		self.app = app
		app.config.setdefault("COMPRESS_MIN_SIZE", 500)
		app.config.setdefault("COMPRESS_FLAG", True)
		app.config.setdefault("COMPRESS_LEVEL_STATIC", 11)
		app.config.setdefault("COMPRESS_LEVEL_DYNAMIC", 5)
		app.config.setdefault("COMPRESS_VERBOSE_LOGGING", False)
		if app.config["COMPRESS_FLAG"]:
			app.after_request(self.after_request)
		self.log(0, "Squeeze.init_app(app) called")


	def compress(self, response, quality):
		self.log(1, f"compress called with args:")
		self.log(2, f"response: {response}")
		self.log(2, f"quality: {quality}")
		data = bytes()
		if response.mimetype == "application/javascript":
			self.log(2, "Mimetype: javascript")
			data = response.get_data(as_text=True)
			data = jsmin(data, keep_bang_comments=False)
			data = bytes(data, encoding="utf-8")
		elif response.mimetype == "application/json":
			self.log(2, "Mimetype: json")
			data = response.get_data(as_text=True)
			data = jsmin(data, keep_bang_comments=False)
			data = bytes(data, encoding="utf-8")
		elif response.mimetype == "text/css":
			self.log(2, "Mimetype: css")
			data = response.get_data(as_text=True)
			data = cssmin(data, keep_bang_comments=False)
			data = bytes(data, encoding="utf-8")
		else:
			self.log(2, "Mimetype: generic")
			data = response.get_data()
		# 0 <= quality <= 11
		return brotli.compress(data, quality=quality)


	def get_and_cache_response(self, app, response):
		"""
			Only call this function if you also want to cache the response.
			Dynamically generated pages should not be cached, since the will unnceccesarily fill the cache
		"""
		key = hashlib.md5(response.get_data()).hexdigest()
		self.log(1, f"Response {response} has cache key: {key}")
		
		if key not in self.cache:
			self.log(2, "NEW response. cache and return it.")

			self.cache[key] = self.compress(response, app.config["COMPRESS_LEVEL_STATIC"])
		else:
			self.log(2, "LOAD response from cache")
		return self.cache[key]


	def after_request(self, response):
		self.log(0, f"after_request called with response: {response}")
		app = self.app or current_app
		if "br" not in request.headers.get("Accept-Encoding", "").lower():
			self.log(1, "Requester does not accept Brotli encoded responses. RETURN")
			return response
		if not (200 <= response.status_code and response.status_code < 300):
			self.log(1, "Response status code is not ok. RETURN")
			return response
		if response.content_length is not None:
			if response.content_length < app.config["COMPRESS_MIN_SIZE"]:
				self.log(1, "Response size is smaller than the defined minimum. RETURN")
				return response
		if "Content-Encoding" in response.headers:
			self.log(1, "Response already encoded. RETURN")
			return response

		response.direct_passthrough = False

		# Only use caching for static files.
		if "static" in str(request):
			self.log(1, f"STATIC requested: {request}")
			self.log(2, "load from cache or cache response")
			cached = self.get_and_cache_response(app, response)
			response.data = cached
		else:
			# For dynamic files, only use compression
			self.log(1, f"DYNAMIC requested: {request}")
			squeezed = self.compress(response, app.config["COMPRESS_LEVEL_DYNAMIC"])
			response.data = squeezed

		response.headers["Content-Encoding"] = "br"
		response.headers["Content-Length"] = response.content_length

		self.log(1, f"Return response: {response}")

		vary = response.headers.get("Vary")
		if vary:
			if "accept-encoding" not in vary.lower():
				response.headers["Vary"] = f"{vary}, Accept-Encoding"
		else:
			response.headers["Vary"] = "Accept-Encoding"
		return response