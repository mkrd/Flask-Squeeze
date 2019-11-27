from flask import current_app, request
import hashlib
import brotli
from rjsmin import jsmin
from rcssmin import cssmin


class Squeeze(object):
    def __init__(self, app=None):
        self.cache = {}
        self.app = app
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        app.config.setdefault("COMPRESS_MIN_SIZE", 500)
        app.config.setdefault("COMPRESS_FLAG", True)
        # Do only minimal compression for development purposes
        app.config.setdefault("COMPRESS_LEVEL_STATIC", 11)
        app.config.setdefault("COMPRESS_LEVEL_DYNAMIC", 5)
        if app.config["COMPRESS_FLAG"]:
            app.after_request(self.after_request)


    def compress(self, response, quality):
        # 0 <= quality <= 11
        if response.mimetype == "application/javascript":
            data = response.get_data(as_text=True)
            data = jsmin(data, keep_bang_comments=False)
            data = bytes(data, encoding="utf-8")
            return brotli.compress(data, quality=quality)
        if response.mimetype == "application/json":
            data = response.get_data(as_text=True)
            data = jsmin(data, keep_bang_comments=False)
            data = bytes(data, encoding="utf-8")
            return brotli.compress(data, quality=quality)
        if response.mimetype == "text/css":
            data = response.get_data(as_text=True)
            data = cssmin(data, keep_bang_comments=False)
            data = bytes(data, encoding="utf-8")
            return brotli.compress(data, quality=quality)
        data = response.get_data()
        return brotli.compress(data, quality=quality)


    def retrieve_from_cache(self, app, request, response):
        key = hashlib.md5(response.get_data()).hexdigest()
        if key not in self.cache:
            self.cache[key] = self.compress(response, app.config["COMPRESS_LEVEL_STATIC"])
            return self.cache[key]
        else:
            log(f"\tSucessfully retrieved from cache.")
            return self.cache[key]


    def after_request(self, response):
        app = self.app or current_app
        if "br" not in request.headers.get("Accept-Encoding", "").lower():
            return response
        if not 200 <= response.status_code < 300:
            return response
        if response.content_length is not None:
            if response.content_length < app.config["COMPRESS_MIN_SIZE"]:
                return response
        if "Content-Encoding" in response.headers:
            return response

        response.direct_passthrough = False

        # Only use caching for static files.
        if "/static/" in str(request):
            print("STATIC RESOURCE")
            cached = self.retrieve_from_cache(app, request, response)
            response.data = cached
        else:
            # For dynamic files, only use compression
            squeezed = self.compress(response, app.config["COMPRESS_LEVEL_DYNAMIC"])
            response.data = squeezed

        response.headers["Content-Encoding"] = "br"
        response.headers["Content-Length"] = response.content_length

        vary = response.headers.get("Vary")
        if vary:
            if "accept-encoding" not in vary.lower():
                response.headers["Vary"] = f"{vary}, Accept-Encoding"
        else:
            response.headers["Vary"] = "Accept-Encoding"
        return response