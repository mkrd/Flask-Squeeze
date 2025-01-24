from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from flask import Response

	from flask_squeeze.models import Encoding


def add_breach_exploit_protection_header(response: Response) -> None:
	"""
	Protect against BREACH attack by adding random padding to the response.
	"""
	padding_length = secrets.randbelow(128) + 1
	rand_str = secrets.token_urlsafe(padding_length)
	response.headers["X-Breach-Exploit-Protection-Padding"] = rand_str


def update_response_headers(
	response: Response,
	original_content_length: int,
	encode_choice: Encoding | None,
) -> None:
	"""
	Set the Content-Length header if it has changed.
	Set the Content-Encoding header if compressed data is served.
	"""
	assert not response.direct_passthrough  # At least one of minify or compress was run

	if encode_choice is not None:
		response.headers["Content-Encoding"] = encode_choice.value
		vary = {x.strip() for x in response.headers.get("Vary", "").split(",")}
		vary.add("Accept-Encoding")
		vary.discard("")
		response.headers["Vary"] = ",".join(vary)

	if original_content_length != response.content_length:
		response.headers["Content-Length"] = response.content_length
