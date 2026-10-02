from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from .compress import CompressionStats
from .minify import MinificationStats
from .plan import Compression, Encoding, Minification, SqueezePlan
from .squeeze import SqueezeResult

FILENAME_PART_COUNT = 4
NOT_APPLIED_MARKER = "none"
"""Filename part for a step (compression or minification) the plan does not apply"""

JsonFieldT = TypeVar("JsonFieldT")

CacheSlot = tuple[str, Encoding | None]
"""Request path hash and encoding. A slot holds one entry: the variant of the current config."""


########################################################################################
#### MARK: Key and entry


@dataclass(frozen=True)
class CacheKey:
	request_path_hash: str
	plan: SqueezePlan

	@classmethod
	def for_request_path(cls, request_path: str, plan: SqueezePlan) -> CacheKey:
		return cls(hashlib.sha256(request_path.encode("utf-8")).hexdigest(), plan)

	@classmethod
	def from_filename_stem(cls, filename_stem: str) -> CacheKey | None:
		"""Inverse of `filename_stem`. Returns None for names this version did not write."""
		parts = filename_stem.split(".")
		if len(parts) != FILENAME_PART_COUNT:
			return None
		request_path_hash, encoding, minification, level = parts
		known_encodings = {e.value for e in Encoding} | {NOT_APPLIED_MARKER}
		known_minifications = {m.value for m in Minification} | {NOT_APPLIED_MARKER}
		if encoding not in known_encodings or minification not in known_minifications:
			return None
		if encoding == NOT_APPLIED_MARKER and minification == NOT_APPLIED_MARKER:
			return None
		if (encoding == NOT_APPLIED_MARKER) != (level == NOT_APPLIED_MARKER):
			return None
		compression = None
		if encoding != NOT_APPLIED_MARKER:
			selected_encoding = Encoding(encoding)
			if level not in {str(valid_level) for valid_level in range(selected_encoding.max_level + 1)}:
				return None
			compression = Compression(selected_encoding, int(level))
		plan = SqueezePlan(
			compression=compression,
			minification=None if minification == NOT_APPLIED_MARKER else Minification(minification),
		)
		return cls(request_path_hash, plan)

	@property
	def filename_stem(self) -> str:
		compression = self.plan.compression
		encoding = compression.encoding.value if compression else NOT_APPLIED_MARKER
		level = str(compression.level) if compression else NOT_APPLIED_MARKER
		minification = self.plan.minification.value if self.plan.minification else NOT_APPLIED_MARKER
		return f"{self.request_path_hash}.{encoding}.{minification}.{level}"

	@property
	def slot(self) -> CacheSlot:
		return self.request_path_hash, self.plan.compression.encoding if self.plan.compression else None


@dataclass(frozen=True)
class CacheEntry:
	key: CacheKey
	original_body_hash: str
	"""sha256 of the response body before squeezing"""
	squeeze_result: SqueezeResult


########################################################################################
#### MARK: Metadata


class InvalidMetadataError(Exception):
	"""The .meta file was not written by this version."""


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
	"""Content of a .meta file. Its .cache file holds the squeezed body."""

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


def _write_atomically(path: Path, content: bytes) -> None:
	"""Other processes sharing the cache dir never see a half written file."""
	with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as f:
		f.write(content)
	Path(f.name).replace(path)


def _delete_entry_files(cache_dir: Path, filename_stem: str) -> None:
	for suffix in (".meta", ".cache"):
		(cache_dir / f"{filename_stem}{suffix}").unlink(missing_ok=True)


def _entry_from_file_contents(filename_stem: str, metadata_json: str, squeezed_body: bytes) -> CacheEntry | None:
	"""Returns None if the files were not written by this version, or do not belong together."""
	key = CacheKey.from_filename_stem(filename_stem)
	metadata = CacheMetadata.from_json(metadata_json)
	if key is None or metadata is None:
		return None
	if hashlib.sha256(squeezed_body).hexdigest() != metadata.squeezed_body_hash:
		return None
	if (metadata.minification_stats is None) != (key.plan.minification is None):
		return None
	if (metadata.compression_stats is None) != (key.plan.compression is None):
		return None
	if (
		metadata.compression_stats is not None
		and key.plan.compression is not None
		and metadata.compression_stats.level != key.plan.compression.level
	):
		return None
	squeeze_result = SqueezeResult(squeezed_body, metadata.minification_stats, metadata.compression_stats)
	return CacheEntry(key, metadata.original_body_hash, squeeze_result)


def _load_entries_from_disk(cache_dir: Path) -> list[CacheEntry]:
	entries: list[CacheEntry] = []
	for meta_file in cache_dir.glob("*.meta"):
		try:
			metadata_json = meta_file.read_text(encoding="utf-8")
			squeezed_body = meta_file.with_suffix(".cache").read_bytes()
		except FileNotFoundError:
			continue  # Another process sharing cache_dir deleted this entry
		except UnicodeDecodeError:
			_delete_entry_files(cache_dir, meta_file.stem)
			continue
		entry = _entry_from_file_contents(meta_file.stem, metadata_json, squeezed_body)
		if entry is None:
			_delete_entry_files(cache_dir, meta_file.stem)
			continue
		entries.append(entry)
	return entries


########################################################################################
#### MARK: Cache


class StaticFileCache:
	"""Thread-safe cache of squeezed static files, optionally persisted to `cache_dir`."""

	def __init__(self, cache_dir: Path | None) -> None:
		self._cache_dir = cache_dir
		self._entries_by_slot: dict[CacheSlot, CacheEntry] = {}
		self._lock = threading.Lock()

		if cache_dir is None:
			return
		cache_dir.mkdir(parents=True, exist_ok=True)
		for entry in _load_entries_from_disk(cache_dir):
			if entry.key.slot in self._entries_by_slot:
				_delete_entry_files(cache_dir, entry.key.filename_stem)
				continue
			self._entries_by_slot[entry.key.slot] = entry

	def get(self, key: CacheKey) -> CacheEntry | None:
		with self._lock:
			entry = self._entries_by_slot.get(key.slot)
		if entry is None or entry.key != key:
			return None
		return entry

	def set(self, entry: CacheEntry) -> None:
		"""Store the entry, replacing the entry of another variant in its slot."""
		with self._lock:
			previous_entry = self._entries_by_slot.get(entry.key.slot)
			self._entries_by_slot[entry.key.slot] = entry
			if self._cache_dir is None:
				return
			if previous_entry is not None and previous_entry.key != entry.key:
				_delete_entry_files(self._cache_dir, previous_entry.key.filename_stem)
			# .cache before .meta: a .meta file only exists once its .cache is complete
			filename_stem = entry.key.filename_stem
			squeezed_body = entry.squeeze_result.squeezed_body
			_write_atomically(self._cache_dir / f"{filename_stem}.cache", squeezed_body)
			metadata = CacheMetadata(
				original_body_hash=entry.original_body_hash,
				squeezed_body_hash=hashlib.sha256(squeezed_body).hexdigest(),
				minification_stats=entry.squeeze_result.minification_stats,
				compression_stats=entry.squeeze_result.compression_stats,
			)
			_write_atomically(self._cache_dir / f"{filename_stem}.meta", metadata.to_json().encode())
