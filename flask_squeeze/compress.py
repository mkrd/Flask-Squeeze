from __future__ import annotations

import gzip
import time
import zlib
from dataclasses import dataclass

import brotli

from .models import Encoding


@dataclass(frozen=True)
class CompressionInfo:
	encoding: Encoding
	quality: int
	duration: float
	ratio: float

	@property
	def headers(self) -> dict:
		value = "; ".join(
			[
				f"ratio={self.ratio:.1f}x",
				f"qualtiy={self.quality}",
				f"duration={self.duration * 1000:.1f}ms",
			],
		)
		return {"X-Flask-Squeeze-Compress": value}


def compress(
	data: bytes,
	encoding: Encoding,
	quality: int,
) -> tuple[bytes, CompressionInfo]:
	t0 = time.perf_counter()

	if encoding is Encoding.br:
		compressed_data = brotli.compress(data, quality=quality)
	elif encoding is Encoding.deflate:
		compressed_data = zlib.compress(data, level=quality)
	elif encoding is Encoding.gzip:
		compressed_data = gzip.compress(data, compresslevel=quality)
	else:
		msg = f"Unsupported encoding: {encoding}"
		raise ValueError(msg)

	ratio = len(data) / len(compressed_data) if len(compressed_data) > 0 else 1.0

	return compressed_data, CompressionInfo(
		encoding=encoding,
		quality=quality,
		duration=time.perf_counter() - t0,
		ratio=ratio,
	)
