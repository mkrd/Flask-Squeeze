import functools
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Dict, Tuple

from flask import Response, current_app


def _write_benchmark_debug_header(response: Response, header_name: str, t1: float, t2: float) -> None:
	if current_app.config["SQUEEZE_ADD_DEBUG_HEADERS"]:
		dur_ms_str = f"{(t2 - t1) * 1000:.1f}ms"
		response.headers[header_name] = dur_ms_str



@contextmanager
def ctx_add_debug_header(header_name: str, response: Response) -> Generator:
	t1 = time.perf_counter()
	yield
	t2 = time.perf_counter()
	_write_benchmark_debug_header(response, header_name, t1, t2)



class add_debug_header:  # noqa: N801

	def __init__(self, header_name: str) -> None:
		self.header_name = header_name

	def get_response(self, args: Tuple, kwargs: Dict) -> Response:
		for arg in args:
			if isinstance(arg, Response):
				return arg
		for kwarg in kwargs.values():
			if isinstance(kwarg, Response):
				return kwarg
		raise ValueError("You can only deocrate a function with 'add_debug_header' that has a Response as an argument or kwarg.")

	def __call__(self, method: Callable) -> Callable:
		@functools.wraps(method)
		def wrapper(*args, **kwargs):
			if not current_app.config["SQUEEZE_ADD_DEBUG_HEADERS"]:
				return method(*args, **kwargs)

			response = self.get_response(args, kwargs)
			t1 = time.perf_counter()
			res = method(*args, **kwargs)
			t2 = time.perf_counter()

			_write_benchmark_debug_header(response, self.header_name, t1, t2)
			return res
		return wrapper
