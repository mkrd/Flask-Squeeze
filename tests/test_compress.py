from __future__ import annotations

import itertools
import unittest
import zlib
from unittest.mock import patch

import brotli

from flask_squeeze.compress import compress
from flask_squeeze.plan import Compression, Encoding
from flask_squeeze.stats import OperationError, OperationStatus
from tests.sample_app import decompress

BODY = b".box { color: red; margin: 0px; }\n" * 100
GZIP_MTIME_FIELD = slice(4, 8)


class CompressTest(unittest.TestCase):
	def test_round_trip_at_level_bounds(self) -> None:
		for encoding, body in itertools.product(Encoding, (BODY, b"")):
			for level in (0, encoding.max_level):
				with self.subTest(encoding=encoding, level=level, body_length=len(body)):
					compressed, stats = compress(body, Compression(encoding, level))
					if stats.status is OperationStatus.applied:
						self.assertEqual(decompress(compressed, encoding), body)
					else:
						self.assertEqual(stats.status, OperationStatus.skipped_larger)
						self.assertEqual(compressed, body)
					self.assertEqual(stats.level, level)
					self.assertGreaterEqual(stats.duration_seconds, 0)

	def test_size_ratio_is_original_over_compressed(self) -> None:
		compressed, stats = compress(BODY, Compression(Encoding.br, 11))
		self.assertAlmostEqual(stats.size_ratio, len(BODY) / len(compressed))
		self.assertGreater(stats.size_ratio, 1)

	def test_gzip_header_has_no_timestamp(self) -> None:
		# Static variants have strong ETags, so equal input must give equal bytes at any time
		compressed, _ = compress(BODY, Compression(Encoding.gzip, 9))
		self.assertEqual(compressed[GZIP_MTIME_FIELD], bytes(4))

	def test_info_header_format(self) -> None:
		_, stats = compress(BODY, Compression(Encoding.gzip, 9))
		self.assertRegex(
			stats.info_headers["X-Flask-Squeeze-Compress"],
			r"^status=compressed; before=\d+; after=\d+; duration=\d+\.\dms; ratio=\d+\.\dx; level=9$",
		)

	def test_larger_output_is_not_applied(self) -> None:
		for encoding in Encoding:
			with self.subTest(encoding=encoding):
				body, stats = compress(b"x", Compression(encoding, encoding.max_level))
				self.assertEqual(body, b"x")
				self.assertEqual(stats.status, OperationStatus.skipped_larger)
				self.assertEqual(stats.before_bytes, 1)
				self.assertIsNotNone(stats.after_bytes)
				self.assertGreater(stats.after_bytes or 0, stats.before_bytes)
				self.assertIn(
					"status=skipped_compressed_too_large; before=1;", stats.info_headers["X-Flask-Squeeze-Compress"]
				)
				self.assertNotIn("ratio=", stats.info_headers["X-Flask-Squeeze-Compress"])

	def test_compressor_errors_preserve_the_input(self) -> None:
		for encoding, target, error in (
			(Encoding.br, "brotli.compress", brotli.error("invalid input")),
			(Encoding.deflate, "zlib.compress", zlib.error("invalid input")),
			(Encoding.gzip, "gzip.compress", zlib.error("invalid input")),
		):
			with self.subTest(encoding=encoding), patch(target, side_effect=error):
				body, stats = compress(BODY, Compression(encoding, encoding.max_level))
				self.assertEqual(body, BODY)
				self.assertEqual(stats.status, OperationStatus.failed)
				self.assertEqual(stats.error, OperationError.compression_error)
				self.assertIsNone(stats.after_bytes)
				self.assertIn("after=unknown", stats.info_headers["X-Flask-Squeeze-Compress"])
				self.assertIn("status=compression_failed", stats.info_headers["X-Flask-Squeeze-Compress"])
				self.assertNotIn("ratio=", stats.info_headers["X-Flask-Squeeze-Compress"])

	def test_equal_size_output_is_applied(self) -> None:
		with patch("gzip.compress", return_value=b"compressed"):
			body, stats = compress(b"0123456789", Compression(Encoding.gzip, 9))
		self.assertEqual(body, b"compressed")
		self.assertEqual(stats.status, OperationStatus.applied)
