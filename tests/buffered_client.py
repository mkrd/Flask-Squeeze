from __future__ import annotations

from typing import TYPE_CHECKING

from flask.testing import FlaskClient
from typing_extensions import override

if TYPE_CHECKING:
	from werkzeug.test import TestResponse


class BufferedTestClient(FlaskClient):
	"""
	Test client that buffers every response. Buffering closes the app iterator, so
	`send_file` responses release their file handle instead of leaking until garbage
	collection, as tests never call `response.close()` the way a WSGI server does.
	"""

	@override
	def open(
		self, *args: object, buffered: bool = True, follow_redirects: bool = False, **kwargs: object
	) -> TestResponse:
		return super().open(*args, buffered=buffered, follow_redirects=follow_redirects, **kwargs)
