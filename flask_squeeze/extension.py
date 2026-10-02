from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING

from flask import request

from .cache import CacheEntry, CacheKey, StaticFileCache
from .config import SqueezeConfig
from .negotiate import choose_encoding
from .plan import Compression, Minification, ResourceType, SqueezePlan
from .squeeze import SqueezeResult, apply_squeeze_plan

if TYPE_CHECKING:
	from flask import Flask, Response

logger = logging.getLogger(__name__)

EXTENSION_KEY = "squeeze"
CACHE_STATUS_HEADER = "X-Flask-Squeeze-Cache"
UNTOUCHED_SUCCESS_STATUSES = (HTTPStatus.NO_CONTENT, HTTPStatus.RESET_CONTENT, HTTPStatus.PARTIAL_CONTENT)


class Squeeze:
	__slots__ = ()

	def __init__(self, app: Flask | None = None) -> None:
		if app is not None:
			self.init_app(app)

	def init_app(self, app: Flask) -> None:
		"""Read the SQUEEZE_* config once. Changing it after this call has no effect."""
		if EXTENSION_KEY in app.extensions:
			msg = "Flask-Squeeze is already initialized on this app"
			raise RuntimeError(msg)

		config = SqueezeConfig.from_flask_config(app.config)
		squeezer = ResponseSqueezer(config, StaticFileCache(config.cache_dir))
		app.extensions[EXTENSION_KEY] = squeezer
		if config.squeezing_enabled:
			app.after_request(squeezer.after_request)


########################################################################################
#### MARK: Planning


def resource_type_for_endpoint(endpoint: str | None) -> ResourceType:
	"""Responses of the app's and blueprints' static endpoints are static."""
	if endpoint is not None and (endpoint == "static" or endpoint.endswith(".static")):
		return ResourceType.static
	return ResourceType.dynamic


def plan_squeeze(
	config: SqueezeConfig,
	accept_encoding: str | None,
	mimetype: str | None,
	resource_type: ResourceType,
) -> SqueezePlan | None:
	"""Return what to do with a squeezable response, or None if nothing applies."""
	encoding = choose_encoding(accept_encoding) if config.compression_enabled else None
	minification = Minification.for_mimetype(mimetype)
	if minification not in config.enabled_minifications:
		minification = None
	if encoding is None and minification is None:
		return None

	compression = None
	if encoding is not None:
		compression = Compression(encoding, config.compression_level(encoding, resource_type))
	return SqueezePlan(compression, minification)


########################################################################################
#### MARK: Helpers


def _log_for_request(message: str, *args: object) -> None:
	if logger.isEnabledFor(logging.DEBUG):
		logger.debug("%s %s: %s", request.method, request.path, message % args)


def _add_breach_protection_header(response: Response) -> None:
	"""Random length padding, so the response size reveals less about the compressed body."""
	padding_length = secrets.randbelow(128) + 1
	response.headers["X-Flask-Squeeze-Breach-Protection"] = secrets.token_urlsafe(padding_length)


@dataclass(frozen=True)
class ResponseSqueezer:
	"""Per-app state of Flask-Squeeze, registered as the app's after_request hook when enabled."""

	config: SqueezeConfig
	static_cache: StaticFileCache

	####################################################################################
	#### MARK: After Request

	def after_request(self, response: Response) -> Response:
		if not self._is_squeezable(response):
			return response

		# Vary even if this response stays uncompressed: other clients may get a compressed
		# variant, and shared caches must not serve one client's variant to another
		if self.config.compression_enabled:
			response.vary.add("Accept-Encoding")

		resource_type = resource_type_for_endpoint(request.endpoint)
		plan = plan_squeeze(self.config, request.headers.get("Accept-Encoding"), response.mimetype, resource_type)
		if plan is None:
			_log_for_request("skipped, no compression or minification applicable")
			return response

		response.direct_passthrough = False  # Squeezing reads the whole body

		if resource_type is ResourceType.static:
			self._squeeze_static_response(response, plan)
		else:
			self._squeeze_dynamic_response(response, plan)

		self._update_representation_headers(response, plan)

		_log_for_request("squeezed, compression=%s, minification=%s", plan.compression, plan.minification)
		return response

	def _is_squeezable(self, response: Response) -> bool:
		if response.content_length is None:
			_log_for_request("skipped, content length unknown")
			return False

		if response.status_code not in range(200, 300) or response.status_code in UNTOUCHED_SUCCESS_STATUSES:
			_log_for_request("skipped, status code %d", response.status_code)
			return False

		if response.content_length < self.config.min_response_size:
			_log_for_request("skipped, %d bytes is below SQUEEZE_MIN_SIZE", response.content_length)
			return False

		if "Content-Encoding" in response.headers:
			_log_for_request("skipped, response already encoded")
			return False

		return True

	####################################################################################
	#### MARK: Squeezing

	def _write_squeeze_result(self, response: Response, squeeze_result: SqueezeResult) -> None:
		response.set_data(squeeze_result.squeezed_body)
		if not self.config.info_headers_enabled:
			return
		if squeeze_result.minification_stats is not None:
			response.headers.update(squeeze_result.minification_stats.info_headers)
		if squeeze_result.compression_stats is not None:
			response.headers.update(squeeze_result.compression_stats.info_headers)

	def _set_cache_status_header(self, response: Response, cache_status: str) -> None:
		if self.config.info_headers_enabled:
			response.headers[CACHE_STATUS_HEADER] = cache_status

	def _squeeze_dynamic_response(self, response: Response, plan: SqueezePlan) -> None:
		self._write_squeeze_result(response, apply_squeeze_plan(response.get_data(), plan))
		if plan.compression is not None:
			_add_breach_protection_header(response)

	def _squeeze_static_response(self, response: Response, plan: SqueezePlan) -> None:
		"""Serve from the cache while the original body is unchanged, otherwise squeeze and cache it."""
		original_body = response.get_data()
		original_body_hash = hashlib.sha256(original_body).hexdigest()
		cache_key = CacheKey.for_request_path(request.path, plan)

		cached_entry = self.static_cache.get(cache_key)
		if cached_entry is not None and cached_entry.original_body_hash == original_body_hash:
			_log_for_request("static cache hit")
			self._write_squeeze_result(response, cached_entry.squeeze_result)
			self._set_cache_status_header(response, "HIT")
			return

		_log_for_request("static cache miss, squeezing")
		squeeze_result = apply_squeeze_plan(original_body, plan)
		self._write_squeeze_result(response, squeeze_result)
		self._set_cache_status_header(response, "MISS")
		self.static_cache.set(CacheEntry(cache_key, original_body_hash, squeeze_result))

	####################################################################################
	#### MARK: Headers

	@staticmethod
	def _update_representation_headers(response: Response, plan: SqueezePlan) -> None:
		"""Make the headers describe the squeezed body instead of the original one."""
		if plan.compression is not None:
			response.headers["Content-Encoding"] = plan.compression.encoding.value

		# Byte ranges of the squeezed body cannot be served, the Range handling works on the original
		response.headers.pop("Accept-Ranges", None)

		etag, is_weak = response.get_etag()
		if etag is None:
			return
		response.set_etag(f"{etag}-{plan.etag_suffix}", weak=bool(is_weak))
		# The view compared If-None-Match against the original ETag, so redo it with the new one
		response.make_conditional(request)
