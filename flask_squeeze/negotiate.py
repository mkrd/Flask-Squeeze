from __future__ import annotations

from werkzeug.datastructures import Accept
from werkzeug.http import parse_accept_header

from .plan import Encoding

# On equal client quality values, the first entry wins.
ENCODING_PREFERENCE_ORDER = (Encoding.br, Encoding.gzip, Encoding.deflate)


def choose_encoding(accept_encoding: str | None) -> Encoding | None:
	"""Return the encoding the client prefers most, or None if it accepts none of them."""
	accepted_encodings = parse_accept_header(accept_encoding, Accept)
	best_encoding: Encoding | None = None
	best_quality = 0.0
	for encoding in ENCODING_PREFERENCE_ORDER:
		quality = accepted_encodings.quality(encoding.value)
		if quality > best_quality:
			best_encoding = encoding
			best_quality = quality
	return best_encoding
