from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from .models import Encoding


@dataclass(frozen=True)
class CacheKey:
	path: str
	encoding: Encoding | None

	@property
	def normalized(self) -> str:
		flat_path = self.path.replace("/", "_")
		encoding = self.encoding.value if self.encoding else "none"
		return f"{flat_path}.{encoding}"


@dataclass(frozen=True)
class CachedData:
	original_hash: str
	data: bytes


@dataclass
class Cache:
	data: dict[str, tuple[str, bytes]]
	""" Maps request path to original data hash and compressed bytes """

	def get(self, cache_key: CacheKey) -> CachedData | None:
		"""Get the cached hash and data for a given cache key."""

		if cache_key.normalized not in self.data:
			return None

		original_hash, data = self.data[cache_key.normalized]
		return CachedData(original_hash, data)

	def set(self, cache_key: CacheKey, original_hash: str, data: bytes) -> None:
		"""Set the cached data for a given cache key."""

		self.data[cache_key.normalized] = (original_hash, data)
