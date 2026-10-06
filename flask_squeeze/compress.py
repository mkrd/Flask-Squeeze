from __future__ import annotations

import gzip
import time
import zlib
from dataclasses import dataclass

import brotli

from .plan import Compression, Encoding
from .stats import InfoStatus, OperationError, OperationStats, OperationStatus


@dataclass(frozen=True)
class CompressionStats(OperationStats):
	level: int

	@property
	def info_headers(self) -> dict[str, str]:
		fields = self.info_fields(
			success=InfoStatus.compressed,
			failure=InfoStatus.compression_failed,
			skipped=InfoStatus.skipped_compressed_too_large,
		)
		value = "; ".join((*fields, f"level={self.level}"))
		return {"X-Flask-Squeeze-Compress": value}


def _compress_body(body: bytes, compression: Compression) -> bytes:
	match compression.encoding:
		case Encoding.br:
			return brotli.compress(body, quality=compression.level)
		case Encoding.deflate:
			return zlib.compress(body, level=compression.level)
		case Encoding.gzip:
			# A fixed mtime makes the output deterministic,
			# as required by the strong ETag of static files
			return gzip.compress(body, compresslevel=compression.level, mtime=0)


def compress(body: bytes, compression: Compression) -> tuple[bytes, CompressionStats]:
	start_time = time.perf_counter()
	try:
		compressed_body = _compress_body(body, compression)
	except (brotli.error, zlib.error):
		return body, CompressionStats(
			level=compression.level,
			duration_seconds=time.perf_counter() - start_time,
			before_bytes=len(body),
			after_bytes=None,
			error=OperationError.compression_error,
		)

	stats = CompressionStats(
		level=compression.level,
		duration_seconds=time.perf_counter() - start_time,
		before_bytes=len(body),
		after_bytes=len(compressed_body),
	)
	return (compressed_body if stats.status is OperationStatus.applied else body), stats
