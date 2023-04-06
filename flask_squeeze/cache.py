from typing import Dict, Tuple, Union

from .log import d_log
from .models import Encoding, Minifcation


class MemoryCache:
	data: Dict[Tuple[str, Encoding, Minifcation], bytes]


	def __init__(self) -> None:
		self.data = {}


	def __repr__(self) -> str:
		keys = ", ".join("-".join([str(v) for v in key]) for key in self.data)
		return f"Cache({keys})"


	@d_log(level=2, with_args=[1, 2, 3])
	def get(self,
			request_path: str,
			encoding: Encoding,
			minification: Minifcation,
	) -> Union[bytes, None]:
		e = encoding.value if encoding else "none"
		m = minification.value if minification else "none"
		return self.data.get((request_path, e, m), None)


	@d_log(level=2, with_args=[1, 2, 3])
	def insert(self,
			request_path: str,
			encoding: Encoding,
			minification: Minifcation,
			value: bytes,
	) -> None:
		e = encoding.value if encoding else "none"
		m = minification.value if minification else "none"
		self.data[(request_path, e, m)] = value
