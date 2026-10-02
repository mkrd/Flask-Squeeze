from __future__ import annotations

import gzip
import time
import zlib
from dataclasses import dataclass

import brotli

from .plan import Compression, Encoding


@dataclass(frozen=True)
class CompressionStats:
	level: int
	duration_seconds: float
	size_ratio: float
	"""Original size divided by compressed size"""

	@property
	def info_headers(self) -> dict[str, str]:
		value = "; ".join(
			[
				f"ratio={self.size_ratio:.1f}x",
				f"level={self.level}",
				f"duration={self.duration_seconds * 1000:.1f}ms",
			],
		)
		return {"X-Flask-Squeeze-Compress": value}


def compress(body: bytes, compression: Compression) -> tuple[bytes, CompressionStats]:
	start_time = time.perf_counter()

	match compression.encoding:
		case Encoding.br:
			compressed_body = brotli.compress(body, quality=compression.level)
		case Encoding.deflate:
			compressed_body = zlib.compress(body, level=compression.level)
		case Encoding.gzip:
			# A fixed mtime makes the output deterministic,
			# as required by the strong ETag of static files
			compressed_body = gzip.compress(body, compresslevel=compression.level, mtime=0)

	size_ratio = len(body) / len(compressed_body) if len(compressed_body) > 0 else 1.0

	return compressed_body, CompressionStats(
		level=compression.level,
		duration_seconds=time.perf_counter() - start_time,
		size_ratio=size_ratio,
	)
