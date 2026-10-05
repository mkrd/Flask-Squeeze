from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import os
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import TypeVar

from .compress import CompressionStats
from .minify import MinificationStats
from .plan import Compression, Encoding, Minification, SqueezePlan
from .squeeze import SQUEEZE_FINGERPRINT, SqueezeResult, apply_squeeze_plan

FILENAME_PART_COUNT = 5
CACHE_FORMAT_MAGIC = b"FSQ1"
METADATA_LENGTH_BYTES = 4
CACHE_HEADER_BYTES = len(CACHE_FORMAT_MAGIC) + METADATA_LENGTH_BYTES
NOT_APPLIED_MARKER = "none"
"""Filename part for a step (compression or minification) the plan does not apply"""

JsonFieldT = TypeVar("JsonFieldT")

CacheSlot = tuple[str, Encoding | None]
"""Request path hash and encoding. A slot holds one entry: the variant of the current config."""


########################################################################################
#### MARK: Key and entry


def _compression_from_filename(encoding: Encoding, level: str) -> Compression:
	if not level.isascii() or not level.isdecimal() or len(level) > len(str(encoding.max_level)):
		msg = "Invalid compression level in cache filename"
		raise ValueError(msg)
	parsed_level = int(level)
	if str(parsed_level) != level:
		msg = "Noncanonical compression level in cache filename"
		raise ValueError(msg)
	return Compression(encoding, parsed_level)


@dataclass(frozen=True)
class CacheKey:
	request_path_hash: str
	plan: SqueezePlan
	squeeze_fingerprint: str

	@classmethod
	def for_request_path(cls, request_path: str, plan: SqueezePlan) -> CacheKey:
		return cls(hashlib.sha256(request_path.encode("utf-8")).hexdigest(), plan, SQUEEZE_FINGERPRINT)

	@classmethod
	def from_filename_stem(cls, filename_stem: str) -> CacheKey | None:
		"""Inverse of `filename_stem`. Returns None for names this version did not write."""
		parts = filename_stem.split(".")
		if len(parts) != FILENAME_PART_COUNT:
			return None
		request_path_hash, squeeze_fingerprint, encoding, minification, level = parts
		known_encodings = {e.value for e in Encoding} | {NOT_APPLIED_MARKER}
		known_minifications = {m.value for m in Minification} | {NOT_APPLIED_MARKER}
		if (
			squeeze_fingerprint != SQUEEZE_FINGERPRINT
			or encoding not in known_encodings
			or minification not in known_minifications
		):
			return None
		if encoding == NOT_APPLIED_MARKER and minification == NOT_APPLIED_MARKER:
			return None
		if (encoding == NOT_APPLIED_MARKER) != (level == NOT_APPLIED_MARKER):
			return None
		compression = None
		if encoding != NOT_APPLIED_MARKER:
			try:
				compression = _compression_from_filename(Encoding(encoding), level)
			except ValueError:
				return None
		plan = SqueezePlan(
			compression=compression,
			minification=None if minification == NOT_APPLIED_MARKER else Minification(minification),
		)
		return cls(request_path_hash, plan, squeeze_fingerprint)

	@property
	def filename_stem(self) -> str:
		compression = self.plan.compression
		encoding = compression.encoding.value if compression else NOT_APPLIED_MARKER
		level = str(compression.level) if compression else NOT_APPLIED_MARKER
		minification = self.plan.minification.value if self.plan.minification else NOT_APPLIED_MARKER
		return f"{self.request_path_hash}.{self.squeeze_fingerprint}.{encoding}.{minification}.{level}"

	@property
	def slot(self) -> CacheSlot:
		return self.request_path_hash, self.plan.compression.encoding if self.plan.compression else None


@dataclass(frozen=True)
class CacheEntry:
	key: CacheKey
	original_body_hash: str
	"""sha256 of the response body before squeezing"""
	squeeze_result: SqueezeResult

	def __post_init__(self) -> None:
		plan = self.key.plan
		result = self.squeeze_result
		if (result.minification_stats is None) != (plan.minification is None):
			msg = "Minification statistics must match the cache key's plan"
			raise ValueError(msg)
		if (result.compression_stats is None) != (plan.compression is None):
			msg = "Compression statistics must match the cache key's plan"
			raise ValueError(msg)
		if (
			result.compression_stats is not None
			and plan.compression is not None
			and result.compression_stats.level != plan.compression.level
		):
			msg = "Compression level must match the cache key's plan"
			raise ValueError(msg)

	def to_bytes(self) -> bytes:
		body = self.squeeze_result.squeezed_body
		metadata = CacheMetadata(
			original_body_hash=self.original_body_hash,
			squeezed_body_hash=hashlib.sha256(body).hexdigest(),
			minification_stats=self.squeeze_result.minification_stats,
			compression_stats=self.squeeze_result.compression_stats,
		)
		metadata_bytes = metadata.to_json().encode("utf-8")
		return CACHE_FORMAT_MAGIC + len(metadata_bytes).to_bytes(METADATA_LENGTH_BYTES, "big") + metadata_bytes + body

	@classmethod
	def from_bytes(cls, filename_stem: str, content: bytes) -> CacheEntry | None:
		"""Reject incompatible, incomplete, or corrupted cache files."""
		if len(content) < CACHE_HEADER_BYTES or not content.startswith(CACHE_FORMAT_MAGIC):
			return None
		metadata_length = int.from_bytes(content[len(CACHE_FORMAT_MAGIC) : CACHE_HEADER_BYTES], "big")
		body_offset = CACHE_HEADER_BYTES + metadata_length
		if body_offset > len(content):
			return None
		try:
			metadata_json = content[CACHE_HEADER_BYTES:body_offset].decode("utf-8")
		except UnicodeDecodeError:
			return None
		return cls._from_metadata(filename_stem, metadata_json, content[body_offset:])

	@classmethod
	def _from_metadata(cls, filename_stem: str, metadata_json: str, body: bytes) -> CacheEntry | None:
		key = CacheKey.from_filename_stem(filename_stem)
		metadata = CacheMetadata.from_json(metadata_json)
		if key is None or metadata is None:
			return None
		if hashlib.sha256(body).hexdigest() != metadata.squeezed_body_hash:
			return None
		result = SqueezeResult(body, metadata.minification_stats, metadata.compression_stats)
		try:
			return cls(key, metadata.original_body_hash, result)
		except ValueError:
			return None


########################################################################################
#### MARK: Metadata


class InvalidMetadataError(Exception):
	"""The cache metadata was not written by this version."""


def _required_json_field(json_object: object, key: str, field_type: type[JsonFieldT]) -> JsonFieldT:
	value = _optional_json_field(json_object, key, field_type)
	if value is None:
		raise InvalidMetadataError(key)
	return value


def _optional_json_field(json_object: object, key: str, field_type: type[JsonFieldT]) -> JsonFieldT | None:
	if not isinstance(json_object, dict):
		raise InvalidMetadataError(key)
	value = json_object.get(key)
	if value is not None and not isinstance(value, field_type):
		raise InvalidMetadataError(key)
	return value


def _required_json_level(json_object: object) -> int:
	key = "level"
	level = _required_json_field(json_object, key, int)
	if isinstance(level, bool) or level < 0:
		raise InvalidMetadataError(key)
	return level


def _required_json_statistic(json_object: object, key: str) -> float:
	value = _required_json_field(json_object, key, float)
	if not math.isfinite(value) or value < 0:
		raise InvalidMetadataError(key)
	return value


@dataclass(frozen=True)
class CacheMetadata:
	"""JSON metadata preceding the squeezed body in a cache file."""

	original_body_hash: str
	squeezed_body_hash: str
	minification_stats: MinificationStats | None
	compression_stats: CompressionStats | None

	def to_json(self) -> str:
		return json.dumps(dataclasses.asdict(self))

	@classmethod
	def from_json(cls, text: str) -> CacheMetadata | None:
		"""Inverse of `to_json`. Returns None for content this version did not write."""
		try:
			metadata: object = json.loads(text)
		except (ValueError, RecursionError):
			return None
		try:
			minification = _optional_json_field(metadata, "minification_stats", dict)
			compression = _optional_json_field(metadata, "compression_stats", dict)
			return cls(
				original_body_hash=_required_json_field(metadata, "original_body_hash", str),
				squeezed_body_hash=_required_json_field(metadata, "squeezed_body_hash", str),
				minification_stats=None
				if minification is None
				else MinificationStats(
					duration_seconds=_required_json_statistic(minification, "duration_seconds"),
					size_ratio=_required_json_statistic(minification, "size_ratio"),
				),
				compression_stats=None
				if compression is None
				else CompressionStats(
					level=_required_json_level(compression),
					duration_seconds=_required_json_statistic(compression, "duration_seconds"),
					size_ratio=_required_json_statistic(compression, "size_ratio"),
				),
			)
		except InvalidMetadataError:
			return None


########################################################################################
#### MARK: Disk


def _write_entry_to_disk(path: Path, content: bytes) -> None:
	file_descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
	temporary_path = Path(temporary_name)
	try:
		with os.fdopen(file_descriptor, "wb") as temporary_file:
			temporary_file.write(content)
		temporary_path.replace(path)
	finally:
		temporary_path.unlink(missing_ok=True)


def _delete_entry_files(cache_dir: Path, filename_stem: str) -> None:
	for suffix in (".meta", ".cache"):
		(cache_dir / f"{filename_stem}{suffix}").unlink(missing_ok=True)


def _load_entries_from_disk(cache_dir: Path) -> list[CacheEntry]:
	entries: list[CacheEntry] = []
	for cache_file in cache_dir.glob("*.cache"):
		try:
			content = cache_file.read_bytes()
		except FileNotFoundError:
			continue
		entry = CacheEntry.from_bytes(cache_file.stem, content)
		if entry is None:
			_delete_entry_files(cache_dir, cache_file.stem)
			continue
		entries.append(entry)
	for meta_file in cache_dir.glob("*.meta"):
		meta_file.unlink(missing_ok=True)
	return entries


########################################################################################
#### MARK: Cache


class CacheStatus(Enum):
	hit = "HIT"
	miss = "MISS"


@dataclass(frozen=True)
class CachedSqueezeResult:
	squeeze_result: SqueezeResult
	status: CacheStatus


class StaticFileCache:
	"""Thread-safe cache of squeezed static files, optionally persisted to `cache_dir`."""

	def __init__(self, cache_dir: Path | None) -> None:
		self._cache_dir = cache_dir
		self._entries_by_slot: dict[CacheSlot, CacheEntry] = {}
		self._lock = Lock()

		if cache_dir is None:
			return
		cache_dir.mkdir(parents=True, exist_ok=True)
		for entry in _load_entries_from_disk(cache_dir):
			if entry.key.slot in self._entries_by_slot:
				_delete_entry_files(cache_dir, entry.key.filename_stem)
				continue
			self._entries_by_slot[entry.key.slot] = entry

	def squeeze(self, key: CacheKey, original_body: bytes) -> CachedSqueezeResult:
		original_body_hash = hashlib.sha256(original_body).hexdigest()
		entry = self.get(key)
		if entry is not None and entry.original_body_hash == original_body_hash:
			return CachedSqueezeResult(entry.squeeze_result, CacheStatus.hit)

		squeeze_result = apply_squeeze_plan(original_body, key.plan)
		self.set(CacheEntry(key, original_body_hash, squeeze_result))
		return CachedSqueezeResult(squeeze_result, CacheStatus.miss)

	def get(self, key: CacheKey) -> CacheEntry | None:
		with self._lock:
			entry = self._entries_by_slot.get(key.slot)
			if entry is None or entry.key != key:
				return None
			return entry

	def set(self, entry: CacheEntry) -> None:
		"""Store the entry, replacing the entry of another variant in its slot."""
		with self._lock:
			if self._cache_dir is None:
				self._entries_by_slot[entry.key.slot] = entry
				return
			content = entry.to_bytes()
			path = self._cache_dir / f"{entry.key.filename_stem}.cache"
			_write_entry_to_disk(path, content)
			previous_entry = self._entries_by_slot.get(entry.key.slot)
			if previous_entry is not None and previous_entry.key != entry.key:
				_delete_entry_files(self._cache_dir, previous_entry.key.filename_stem)
			self._entries_by_slot[entry.key.slot] = entry
