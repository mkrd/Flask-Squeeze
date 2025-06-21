from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from pathlib import Path

	from .models import Encoding


########################################################################################
#### MARK: Disk utils


def _save_cache_entry_to_disk(
	cache_dir: Path,
	cache_key: CacheKey,
	original_hash: str,
	data: bytes,
) -> None:
	# Save metadata
	with (cache_dir / f"{cache_key.normalized}.meta").open("w") as f:
		f.write(original_hash)

	# Save data
	with (cache_dir / f"{cache_key.normalized}.cache").open("wb") as f:
		f.write(data)


def _read_cache_data_from_disk(cache_dir: Path) -> dict[str, tuple[str, bytes]]:
	data: dict[str, tuple[str, bytes]] = {}

	for meta_file in cache_dir.glob("*.meta"):
		cache_key = meta_file.stem
		with meta_file.open() as f:
			original_hash = f.read()

		cache_file = meta_file.with_suffix(".cache")
		if cache_file.exists():
			with cache_file.open("rb") as f:
				cached_bytes = f.read()

			data[cache_key] = (original_hash, cached_bytes)

	return data


########################################################################################
#### MARK: Cache


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

	cache_dir: Path | None = None
	""" Directory to store persistent cache files """

	def __post_init__(self) -> None:
		"""Initialize cache directory if specified."""
		if self.cache_dir is not None:
			self.cache_dir.mkdir(parents=True, exist_ok=True)
			self.data.update(_read_cache_data_from_disk(self.cache_dir))

	def get(self, cache_key: CacheKey) -> CachedData | None:
		"""Get the cached hash and data for a given cache key."""

		if cache_key.normalized not in self.data:
			return None

		original_hash, data = self.data[cache_key.normalized]
		return CachedData(original_hash, data)

	def set(self, cache_key: CacheKey, original_hash: str, data: bytes) -> None:
		"""Set the cached data for a given cache key."""

		self.data[cache_key.normalized] = (original_hash, data)

		# Save to disk if persistent caching is enabled
		if self.cache_dir is not None:
			_save_cache_entry_to_disk(self.cache_dir, cache_key, original_hash, data)
