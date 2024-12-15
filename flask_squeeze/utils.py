import secrets

from flask import Response


def add_breach_exploit_protection_header(response: Response) -> None:
	"""
	Protect against BREACH attack by adding random padding to the response.
	"""
	padding_length = secrets.randbelow(128) + 1
	rand_str = secrets.token_urlsafe(padding_length)
	response.headers["X-Breach-Exploit-Protection-Padding"] = rand_str
