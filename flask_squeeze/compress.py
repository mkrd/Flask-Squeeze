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
	encode_choice: Encoding,
	quality: int,
) -> tuple[bytes, CompressionInfo]:
	t0 = time.perf_counter()

	compressors = {
		Encoding.br: lambda d, q: brotli.compress(d, quality=q),
		Encoding.deflate: lambda d, q: zlib.compress(d, level=q),
		Encoding.gzip: lambda d, q: gzip.compress(d, compresslevel=q),
	}

	compressed_data = compressors[encode_choice](data, quality)

	return compressed_data, CompressionInfo(
		encoding=encode_choice,
		quality=quality,
		duration=time.perf_counter() - t0,
		ratio=len(data) / len(compressed_data),
	)
