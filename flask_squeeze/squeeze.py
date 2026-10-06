from __future__ import annotations

import hashlib
import json
import sys
import zlib
from dataclasses import dataclass
from importlib.metadata import version
from typing import TYPE_CHECKING

from .compress import CompressionStats, compress
from .minify import MinificationStats, minification_options_signature, minify

if TYPE_CHECKING:
	from .plan import SqueezePlan

# Increment when squeezing behavior changes without a dependency or option change.
SQUEEZE_REVISION = 2


def squeeze_fingerprint() -> str:
	identity = (
		str(SQUEEZE_REVISION),
		version("flask-squeeze"),
		version("turbohtml"),
		version("brotli"),
		zlib.ZLIB_RUNTIME_VERSION,
		sys.version,
		*minification_options_signature(),
	)
	return hashlib.sha256(json.dumps(identity).encode("utf-8")).hexdigest()


SQUEEZE_FINGERPRINT = squeeze_fingerprint()


@dataclass(frozen=True)
class SqueezeResult:
	squeezed_body: bytes
	minification_stats: MinificationStats | None
	compression_stats: CompressionStats | None


def apply_squeeze_plan(body: bytes, plan: SqueezePlan) -> SqueezeResult:
	"""Minify first, then compress: minified text compresses better."""
	squeezed_body = body

	minification_stats = None
	if plan.minification is not None:
		squeezed_body, minification_stats = minify(squeezed_body, plan.minification)

	compression_stats = None
	if plan.compression is not None:
		squeezed_body, compression_stats = compress(squeezed_body, plan.compression)

	return SqueezeResult(squeezed_body, minification_stats, compression_stats)
