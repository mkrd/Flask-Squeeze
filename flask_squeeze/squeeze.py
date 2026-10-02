from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .compress import CompressionStats, compress
from .minify import MinificationStats, minify

if TYPE_CHECKING:
	from .plan import SqueezePlan


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
