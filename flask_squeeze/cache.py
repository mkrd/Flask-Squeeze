from typing import Dict, Tuple, Union

from .logging import d_log


class Cache:
	data: Dict[Tuple[str, str, bool], bytes]


	def __init__(self) -> None:
		self.data = {}

	def __repr__(self) -> str:
		keys = ", ".join("-".join([str(v) for v in key]) for key in self.data)
		return f"Cache({keys})"


	@d_log(level=2, with_args=[1, 2, 3])
	def get(self,
			request_path: str,
			encoding: str,
			is_minified: bool,
	) -> Union[bytes, None]:
		file = request_path.replace("/static/", "")
		return self.data.get((file, encoding, is_minified), None)


	@d_log(level=2, with_args=[1, 2, 3])
	def insert(self,
			request_path: str,
			encoding: str,
			is_minified: bool,
			value: bytes,
	) -> None:
		file = request_path.replace("/static/", "")
		self.data[(file, encoding, is_minified)] = value
