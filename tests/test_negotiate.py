from __future__ import annotations

import unittest

from flask_squeeze.negotiate import negotiate_encoding
from flask_squeeze.plan import Encoding


class NegotiateEncodingTest(unittest.TestCase):
	def test_client_preference_wins(self) -> None:
		cases: list[tuple[str | None, Encoding | None]] = [
			("gzip;q=0.5, br;q=0.8", Encoding.br),
			("gzip;q=0.8, br;q=0.5", Encoding.gzip),
			("br;q=0, gzip;q=1", Encoding.gzip),
			("deflate", Encoding.deflate),
			("br;q=0.001", Encoding.br),
		]
		for header, expected in cases:
			with self.subTest(header=header):
				self.assertIs(negotiate_encoding(header), expected)

	def test_ties_prefer_brotli_then_gzip_then_deflate(self) -> None:
		cases: list[tuple[str | None, Encoding | None]] = [
			("gzip, br, deflate", Encoding.br),
			("deflate, gzip", Encoding.gzip),
			("gzip;q=0.5, deflate;q=0.5", Encoding.gzip),
			(" gzip ,  br ", Encoding.br),
		]
		for header, expected in cases:
			with self.subTest(header=header):
				self.assertIs(negotiate_encoding(header), expected)

	def test_wildcard_matches_codings_not_listed(self) -> None:
		cases: list[tuple[str | None, Encoding | None]] = [
			("*", Encoding.br),
			("*;q=0.5", Encoding.br),
			("gzip;q=0, *;q=0.5", Encoding.br),
			("br;q=0, *", Encoding.gzip),
			("*;q=0, gzip", Encoding.gzip),
		]
		for header, expected in cases:
			with self.subTest(header=header):
				self.assertIs(negotiate_encoding(header), expected)

	def test_coding_names_are_case_insensitive(self) -> None:
		self.assertIs(negotiate_encoding("GZIP"), Encoding.gzip)
		self.assertIs(negotiate_encoding("Br;q=1"), Encoding.br)

	def test_nothing_acceptable(self) -> None:
		for header in (None, "", "gzip;q=0", "identity", "xgzip", "zstd", ",,,", "*;q=0"):
			with self.subTest(header=header):
				self.assertIsNone(negotiate_encoding(header))
