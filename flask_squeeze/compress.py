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


def compress(
	data: bytes,
	encode_choice: Encoding,
	quality: int,
) -> CompressionResult:
	t0 = time.perf_counter()

	if encode_choice == Encoding.br:
		compressed_data = brotli.compress(data, quality=quality)
	elif encode_choice == Encoding.deflate:
		compressed_data = zlib.compress(data, level=quality)
	elif encode_choice == Encoding.gzip:
		compressed_data = gzip.compress(data, compresslevel=quality)
	else:
		msg = f"Invalid encoding choice {encode_choice}"
		raise ValueError(msg)

	return CompressionResult(
		data=compressed_data,
		encoding=encode_choice,
		quality=quality,
		duration=time.perf_counter() - t0,
		ratio=len(data) / len(compressed_data),
	)


def update_response_with_compressed_data(response: Response, result: CompressionResult) -> None:
	response.set_data(result.data)
	response.headers["X-Flask-Squeeze-Compression-Quality"] = str(result.quality)
	response.headers["X-Flask-Squeeze-Compression-Duration"] = f"{result.duration * 1000:.1f}ms"
	response.headers["X-Flask-Squeeze-Compression-Ratio"] = f"{result.ratio:.1f}x"
