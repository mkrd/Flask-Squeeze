from __future__ import annotations

from enum import Enum

from werkzeug.datastructures import Accept
from werkzeug.http import parse_accept_header

from .plan import Encoding

ENCODING_PREFERENCE_ORDER = (Encoding.br, Encoding.gzip, Encoding.deflate)


class EncodingFallback(Enum):
	identity = "identity"
	not_acceptable = "not-acceptable"


def negotiate_encoding(
	accept_encoding_header: str | None,
	*,
	available_encodings: tuple[Encoding, ...] = ENCODING_PREFERENCE_ORDER,
) -> Encoding | EncodingFallback:
	"""Prefer supported compression unless the client explicitly prefers identity."""

	accepted_encodings = parse_accept_header(accept_encoding_header, Accept)
	explicit_identity_quality = next(
		(quality for coding, quality in accepted_encodings if coding.lower() == "identity"), None
	)
	wildcard_quality = next((quality for coding, quality in accepted_encodings if coding == "*"), None)
	identity_quality = explicit_identity_quality
	if identity_quality is None:
		identity_quality = 0.0 if wildcard_quality == 0 else 1.0

	best_encoding: Encoding | None = None
	best_quality = 0.0

	for encoding in available_encodings:
		quality = accepted_encodings.quality(encoding.value)
		if quality <= best_quality:
			continue
		best_encoding = encoding
		best_quality = quality

	if best_encoding is not None and (explicit_identity_quality is None or best_quality >= identity_quality):
		return best_encoding
	if identity_quality > 0:
		return EncodingFallback.identity
	return EncodingFallback.not_acceptable
