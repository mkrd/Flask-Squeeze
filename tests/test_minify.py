import pytest

from flask_squeeze.minify import minify


def test_minify_invalid_minification() -> None:
	with pytest.raises(ValueError, match="Unsupported minification: unsupported"):
		minify(b"test data", "unsupported")  # type: ignore[arg-type]
