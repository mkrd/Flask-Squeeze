import gzip
import time
import zlib
from dataclasses import dataclass

import brotli
from flask import Response

from flask_squeeze.models import Encoding


@dataclass(frozen=True)
class CompressionResult:
	data: bytes
	encoding: Encoding
	quality: int
	duration: float
	ratio: float

	@property
	def info(self) -> str:
		return "; ".join(
			[
				f"ratio={self.ratio:.1f}x",
				f"qualtiy={self.quality}",
				f"duration={self.duration * 1000:.1f}ms",
			],
		)


def compress(
	data: bytes,
	encode_choice: Encoding,
	quality: int,
) -> CompressionResult:
	t0 = time.perf_counter()

	compressors = {
		Encoding.br: lambda d, q: brotli.compress(d, quality=q),
		Encoding.deflate: lambda d, q: zlib.compress(d, level=q),
		Encoding.gzip: lambda d, q: gzip.compress(d, compresslevel=q),
	}

	compressed_data = compressors[encode_choice](data, quality)

	return CompressionResult(
		data=compressed_data,
		encoding=encode_choice,
		quality=quality,
		duration=time.perf_counter() - t0,
		ratio=len(data) / len(compressed_data),
	)


def update_response_with_compressed_data(response: Response, result: CompressionResult) -> None:
	response.set_data(result.data)
	response.headers["X-Flask-Squeeze-Compress"] = result.info
