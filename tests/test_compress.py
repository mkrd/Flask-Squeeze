import pytest

from flask_squeeze.compress import compress


def test_compress_invalid_encoding() -> None:
	with pytest.raises(ValueError, match="Unsupported encoding: unsupported"):
		compress(b"test data", "unsupported", 5)  # type: ignore[arg-type]
