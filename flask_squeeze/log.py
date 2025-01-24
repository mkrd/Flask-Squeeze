from __future__ import annotations

import functools
import time
from typing import Any, Callable, Union

from flask import Request, current_app, request


def _format_log(
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


def log(level: int, s: str) -> None:
	if current_app.config["SQUEEZE_VERBOSE_LOGGING"]:
		print(_format_log(s, level, request, 92))


class d_log:  # noqa: N801
	"""
	decorator for logging.
	level: indent level
	with_args: list of indices of args that should apppear in the log
	with_kwargs: list of kwarg names that should appear in the log
	"""

	def __init__(
		self,
		level: int = 0,
		with_args: Union[list, None] = None,
		with_kwargs: Union[list, None] = None,
	) -> None:
		self.level = level
		self.with_args = with_args if with_args is not None else []
		self.with_kwargs = with_kwargs if with_kwargs is not None else []

	def __call__(self, method: Callable) -> Callable:
		@functools.wraps(method)
		def wrapper(*args: tuple, **kwargs: dict[str, Any]):
			if not current_app.config["SQUEEZE_VERBOSE_LOGGING"]:
				return method(*args, **kwargs)

			chosen_args = [f"{a}" for i, a in enumerate(args) if i in self.with_args]
			chosen_kwargs = [f"{k}={a}" for k, a in kwargs.items() if k in self.with_kwargs]
			begin_log = f"{method.__name__}({', '.join(chosen_args + chosen_kwargs)}) {{"
			print(_format_log(begin_log, self.level, request, 96))

			t1 = time.perf_counter()
			res = method(*args, **kwargs)
			t2 = time.perf_counter()

			end_log = f"}} -> {((t2 - t1) * 1000):.2f}ms" + ("\n" if self.level == 0 else "")
			print(_format_log(end_log, self.level, request, 96))

			return res

		return wrapper
