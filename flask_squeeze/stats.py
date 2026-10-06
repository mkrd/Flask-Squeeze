from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum, StrEnum


class OperationStatus(Enum):
	applied = "applied"
	skipped_larger = "skipped-larger"
	failed = "failed"


class OperationError(StrEnum):
	invalid_utf8 = "invalid-utf8"
	javascript_parse_error = "javascript-parse-error"
	compression_error = "compression-error"


class InfoStatus(Enum):
	minified = "minified"
	compressed = "compressed"
	minification_failed = "minification_failed"
	compression_failed = "compression_failed"
	skipped_minified_too_large = "skipped_minified_too_large"
	skipped_compressed_too_large = "skipped_compressed_too_large"


@dataclass(frozen=True, kw_only=True)
class OperationStats:
	duration_seconds: float
	before_bytes: int
	after_bytes: int | None
	"""Attempted output size; None when the operation failed before producing output."""
	error: OperationError | None = None

	def __post_init__(self) -> None:
		if not math.isfinite(self.duration_seconds) or self.duration_seconds < 0:
			msg = "Operation duration must be finite and nonnegative"
			raise ValueError(msg)
		if self.before_bytes < 0 or (self.after_bytes is not None and self.after_bytes < 0):
			msg = "Operation sizes must be nonnegative"
			raise ValueError(msg)
		if (self.after_bytes is None) != (self.error is not None):
			msg = "A failed operation must have an error and no output size"
			raise ValueError(msg)

	@property
	def status(self) -> OperationStatus:
		if self.after_bytes is None:
			return OperationStatus.failed
		if self.after_bytes > self.before_bytes:
			return OperationStatus.skipped_larger
		return OperationStatus.applied

	@property
	def size_ratio(self) -> float:
		if not self.after_bytes:
			return 1.0
		return self.before_bytes / self.after_bytes

	def info_fields(self, *, success: InfoStatus, failure: InfoStatus, skipped: InfoStatus) -> tuple[str, ...]:
		match self.status:
			case OperationStatus.applied:
				status = success
			case OperationStatus.failed:
				status = failure
			case OperationStatus.skipped_larger:
				status = skipped
		fields = (
			f"status={status.value}",
			f"before={self.before_bytes}",
			f"after={self.after_bytes if self.after_bytes is not None else 'unknown'}",
			f"duration={self.duration_seconds * 1000:.1f}ms",
		)
		if self.error is not None:
			return (*fields, f"error={self.error.value}")
		if self.status is OperationStatus.skipped_larger:
			return fields
		return (*fields, f"ratio={self.size_ratio:.1f}x")
