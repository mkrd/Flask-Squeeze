from __future__ import annotations

import functools
import time
from typing import TYPE_CHECKING, Any

from flask import Response, current_app

if TYPE_CHECKING:
	from collections.abc import Callable


def _write_benchmark_debug_header(response: Response, header_name: str, t1: float, t2: float) -> None:
	if current_app.config["SQUEEZE_ADD_DEBUG_HEADERS"]:
		dur_ms_str = f"{(t2 - t1) * 1000:.1f}ms"
		response.headers[header_name] = dur_ms_str


class add_debug_header:  # noqa: N801
	def __init__(self, header_name: str) -> None:
		self.header_name = header_name

	def get_response(self, args: tuple, kwargs: dict) -> Response:
		for arg in args:
			if isinstance(arg, Response):
				return arg
		for kwarg in kwargs.values():
			if isinstance(kwarg, Response):
				return kwarg
		msg = "You can only deocrate a function with 'add_debug_header' that has a Response as an argument or kwarg."
		raise ValueError(msg)

	def __call__(self, method: Callable) -> Callable:
		@functools.wraps(method)
		def wrapper(*args: tuple, **kwargs: dict[str, Any]):
			if not current_app.config["SQUEEZE_ADD_DEBUG_HEADERS"]:
				return method(*args, **kwargs)

			response = self.get_response(args, kwargs)
			t1 = time.perf_counter()
			res = method(*args, **kwargs)
			t2 = time.perf_counter()

			_write_benchmark_debug_header(response, self.header_name, t1, t2)
			return res

		return wrapper
