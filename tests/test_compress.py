from __future__ import annotations

import itertools
import unittest

from flask_squeeze.compress import compress
from flask_squeeze.plan import Compression, Encoding
from tests.sample_app import decompress

BODY = b".box { color: red; margin: 0px; }\n" * 100
GZIP_MTIME_FIELD = slice(4, 8)


class CompressTest(unittest.TestCase):
	def test_round_trip_at_level_bounds(self) -> None:
		for encoding, body in itertools.product(Encoding, (BODY, b"")):
			for level in (0, encoding.max_level):
				with self.subTest(encoding=encoding, level=level, body_length=len(body)):
					compressed, stats = compress(body, Compression(encoding, level))
					self.assertEqual(decompress(compressed, encoding), body)
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
			r"^ratio=\d+\.\dx; level=9; duration=\d+\.\dms$",
		)
