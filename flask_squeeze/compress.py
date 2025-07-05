from __future__ import annotations

import gzip
import logging
import time
import zlib
from dataclasses import dataclass

import brotli

from .models import Encoding

logger = logging.getLogger(__name__)


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
	original_size = len(data)

	logger.debug(f"Compressing {original_size} bytes with {encoding.name} (quality={quality})")

	if encoding is Encoding.br:
		compressed_data = brotli.compress(data, quality=quality)
	elif encoding is Encoding.deflate:
		compressed_data = zlib.compress(data, level=quality)
	elif encoding is Encoding.gzip:
		compressed_data = gzip.compress(data, compresslevel=quality)
	else:
		msg = f"Unsupported encoding: {encoding}"
		logger.error(msg)
		raise ValueError(msg)

	ratio = len(data) / len(compressed_data) if len(compressed_data) > 0 else 1.0
	duration = time.perf_counter() - t0

	logger.debug(
		f"Compressed {original_size} -> {len(compressed_data)} bytes ({ratio:.1f}x) in {duration * 1000:.1f}ms"
	)

	return compressed_data, CompressionInfo(
		encoding=encoding,
		quality=quality,
		duration=duration,
		ratio=ratio,
	)
