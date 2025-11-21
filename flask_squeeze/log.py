from __future__ import annotations

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
