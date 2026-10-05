from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING

from .plan import Compression, Encoding, Minification, ResourceType

if TYPE_CHECKING:
	from collections.abc import Mapping

	from flask import Config

CONFIG_KEY_PREFIX = "SQUEEZE_"


def _default_compression_level(encoding: Encoding, resource_type: ResourceType) -> int:
	"""Static files are squeezed once and cached, so they get the best compression."""
	match resource_type:
		case ResourceType.static:
			return encoding.max_level
		case ResourceType.dynamic:
			return 1


DEFAULT_CONFIG: Mapping[str, object] = MappingProxyType(
	{
		"SQUEEZE_COMPRESS": True,
		"SQUEEZE_MIN_SIZE": 500,
		"SQUEEZE_CACHE_DIR": None,
		"SQUEEZE_INFO_HEADERS": False,
		**{minification.enable_config_key: True for minification in Minification},
		**{
			encoding.level_config_key(resource_type): _default_compression_level(encoding, resource_type)
			for encoding in Encoding
			for resource_type in ResourceType
		},
	}
)


########################################################################################
#### MARK: Parsing


def _read_value_or_default(config: Config, key: str) -> object:
	return config.get(key, DEFAULT_CONFIG[key])


def _read_bool(config: Config, key: str) -> bool:
	value = _read_value_or_default(config, key)
	if not isinstance(value, bool):
		msg = f"{key} must be a bool, got {value!r}"
		raise TypeError(msg)
	return value


def _read_int(config: Config, key: str, minimum: int | None = None) -> int:
	value = _read_value_or_default(config, key)
	if not isinstance(value, int) or isinstance(value, bool):
		msg = f"{key} must be an int, got {value!r}"
		raise TypeError(msg)
	if minimum is not None and value < minimum:
		msg = f"{key} must be at least {minimum}, got {value}"
		raise ValueError(msg)
	return value


def _read_compression_level(config: Config, encoding: Encoding, resource_type: ResourceType) -> int:
	key = encoding.level_config_key(resource_type)
	level = _read_int(config, key)
	try:
		return Compression(encoding, level).level
	except ValueError as error:
		msg = f"{key}: {error}"
		raise ValueError(msg) from error


def _read_optional_path(config: Config, key: str) -> Path | None:
	value = _read_value_or_default(config, key)
	if value is None:
		return None
	if not isinstance(value, (str, Path)):
		msg = f"{key} must be a str, Path or None, got {value!r}"
		raise TypeError(msg)
	return Path(value)


########################################################################################
#### MARK: Config


@dataclass(frozen=True)
class SqueezeConfig:
	compression_enabled: bool
	min_response_size: int
	compression_levels: Mapping[tuple[Encoding, ResourceType], int]
	enabled_minifications: frozenset[Minification]
	cache_dir: Path | None
	info_headers_enabled: bool

	def __post_init__(self) -> None:
		levels = dict(self.compression_levels)
		for encoding in Encoding:
			for resource_type in ResourceType:
				Compression(encoding, levels[encoding, resource_type])
		object.__setattr__(self, "compression_levels", MappingProxyType(levels))

	@classmethod
	def from_flask_config(cls, config: Config) -> SqueezeConfig:
		"""Validate and parse the SQUEEZE_* keys, using the defaults for missing ones."""
		unknown_keys = {key for key in config if key.startswith(CONFIG_KEY_PREFIX)} - DEFAULT_CONFIG.keys()
		if unknown_keys:
			msg = f"Unknown Flask-Squeeze config keys: {', '.join(sorted(unknown_keys))}"
			raise ValueError(msg)

		compression_levels = {
			(encoding, resource_type): _read_compression_level(config, encoding, resource_type)
			for encoding in Encoding
			for resource_type in ResourceType
		}

		return cls(
			compression_enabled=_read_bool(config, "SQUEEZE_COMPRESS"),
			min_response_size=_read_int(config, "SQUEEZE_MIN_SIZE", minimum=0),
			compression_levels=compression_levels,
			enabled_minifications=frozenset(m for m in Minification if _read_bool(config, m.enable_config_key)),
			cache_dir=_read_optional_path(config, "SQUEEZE_CACHE_DIR"),
			info_headers_enabled=_read_bool(config, "SQUEEZE_INFO_HEADERS"),
		)

	@property
	def squeezing_enabled(self) -> bool:
		return self.compression_enabled or bool(self.enabled_minifications)

	def compression_level(self, encoding: Encoding, resource_type: ResourceType) -> int:
		return self.compression_levels[(encoding, resource_type)]
