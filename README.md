![Logo](https://github.com/mkrd/Flask-Squeeze/blob/main/assets/logo.png?raw=true)

[![Downloads](https://pepy.tech/badge/flask-squeeze)](https://pepy.tech/project/flask-squeeze)
![Tests](https://github.com/mkrd/Flask-Squeeze/actions/workflows/test.yml/badge.svg)
![Coverage](https://github.com/mkrd/Flask-Squeeze/blob/main/assets/coverage.svg?raw=1)

Flask-Squeeze is a Flask extension that automatically:
- **Minifies** responses with JavaScript, CSS, and HTML content
- **Compresses** responses with brotli, gzip, or deflate, based on browser support (on equal client preference: brotli, then gzip, then deflate)
- **Pads** compressed dynamic responses with a random length header, which makes BREACH style size measurements harder
- **Caches** squeezed static files so they don't need to be re-compressed, in memory and optionally on disk
- **Optimizes performance** with separate compression levels for static and dynamic content
- **Works out-of-the-box** - no changes needed to your existing Flask routes or templates

Responses of the app's and blueprints' `static` endpoints are static, all others are dynamic.

### What gets squeezed
A response is left untouched if any of these hold:
- Its status is not 2xx, or it is 204, 205, or 206 (range responses are served as is)
- Its length is unknown, e.g. a streamed response
- It is smaller than `SQUEEZE_MIN_SIZE`
- It already has a `Content-Encoding`

Squeezed responses get their own ETag per variant (original ETag plus a suffix such as `-minjs-br11`),
and their `Accept-Ranges` header is removed, since byte ranges refer to the original file.
Conditional requests (`If-None-Match`, `If-Modified-Since`, `If-Match`) for static files are answered
against the variant's ETag.

### Text encoding
Minification only supports UTF-8. Responses that declare another charset are compressed, but not minified.
A response that declares UTF-8, which Flask does for all text by default, but is not valid UTF-8 raises a
`UnicodeDecodeError`. A leading byte order mark is removed when minifying.

HTML that does not start with a doctype or an `<html>`, `<head>` or `<body>` tag is minified as a fragment,
so partial responses, such as table rows for htmx, keep all their tags.


Table of Contents
----------------------------------------------------------------------------------------
- [Compatibility](#compatibility)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Contributing](#contributing)


Compatibility
----------------------------------------------------------------------------------------

- Works with Python 3.11 to 3.14


Installation
----------------------------------------------------------------------------------------

```
pip install Flask-Squeeze
```


Quick Start
----------------------------------------------------------------------------------------

```python
from flask import Flask
from flask_squeeze import Squeeze

squeeze = Squeeze()


def create_app():
	app = Flask(__name__)

	# Init Flask-Squeeze
	squeeze.init_app(app)

	# Init all other extensions AFTER Flask-Squeeze. Flask runs after_request hooks
	# in reverse order of registration, so Flask-Squeeze then sees their final response.

	return app
```

That's it! The responses of your Flask app will now get minified and compressed, if the browser supports it.
To control how Flask-Squeeze behaves, the following options exist.
They are read and validated once in `init_app`, so set them before calling it. Changes made afterwards have no effect.


### Basic Options
| Option | Default | Description |
| --- | --- | --- |
| `SQUEEZE_COMPRESS` | `True` | Enable/disable compression |
| `SQUEEZE_MIN_SIZE` | `500` | Minimum response size (bytes) to compress or minify |
| `SQUEEZE_CACHE_DIR` | `None` | Directory for persistent cache (`None` = in-memory only) |
| `SQUEEZE_INFO_HEADERS` | `False` | Add the info headers described below to squeezed responses |

Unknown `SQUEEZE_*` keys raise an error in `init_app`, so a typo in a key name does not go unnoticed.

Each disk cache entry stores metadata and squeezed bytes in one file. Writes use a temporary file in
the same directory, then atomically replace the cache file. A thread lock synchronizes access within
each cache instance; separate processes can overwrite one another without filesystem locks. Invalid
or incompatible cache files are deleted on startup and rebuilt on the next request.

### Info headers
With `SQUEEZE_INFO_HEADERS` enabled, squeezed responses carry:
- `X-Flask-Squeeze-Minify`: minification ratio and duration, e.g. `ratio=1.4x; duration=0.3ms`
- `X-Flask-Squeeze-Compress`: compression ratio, level and duration, e.g. `ratio=3.2x; level=11; duration=4.1ms`
- `X-Flask-Squeeze-Cache`: `HIT` or `MISS`, on static responses only

On a cache hit, the ratio and duration are the ones measured when the file was squeezed.
They expose timing data to every client, so keep them disabled in production.

### Minification Options
| Option | Default | Description |
| --- | --- | --- |
| `SQUEEZE_MINIFY_CSS` | `True` | Enable CSS minification |
| `SQUEEZE_MINIFY_JS` | `True` | Enable JavaScript minification |
| `SQUEEZE_MINIFY_HTML` | `True` | Enable HTML minification |

### Compression Levels
| Option | Default | Range | Description |
| --- | --- | --- | --- |
| `SQUEEZE_LEVEL_BROTLI_STATIC` | `11` | 0-11 | Brotli level for static files |
| `SQUEEZE_LEVEL_BROTLI_DYNAMIC` | `1` | 0-11 | Brotli level for dynamic content |
| `SQUEEZE_LEVEL_GZIP_STATIC` | `9` | 0-9 | Gzip level for static files |
| `SQUEEZE_LEVEL_GZIP_DYNAMIC` | `1` | 0-9 | Gzip level for dynamic content |
| `SQUEEZE_LEVEL_DEFLATE_STATIC` | `9` | 0-9 | Deflate level for static files |
| `SQUEEZE_LEVEL_DEFLATE_DYNAMIC` | `1` | 0-9 | Deflate level for dynamic content |

If compression and all minification options are disabled, Flask-Squeeze does not register its hook at all.

### Example Configuration
```python
app.config.update(
	{
		"SQUEEZE_CACHE_DIR": "./cache/flask_squeeze/",  # Enable persistent caching
		"SQUEEZE_MIN_SIZE": 1000,  # Only compress files > 1KB
	}
)
```

### Logging
Flask-Squeeze logs through the standard `logging` module under the `flask_squeeze` logger.
It emits `DEBUG` records explaining why each response was or was not squeezed.
To see them, configure the logger in your app:
```python
import logging

logging.getLogger("flask_squeeze").setLevel(logging.DEBUG)
```
The records then go to whatever handlers your application has configured,
e.g. via `logging.basicConfig()`.


Contributing
----------------------------------------------------------------------------------------

1. **Report bugs** by opening an issue
2. **Submit pull requests** with improvements
3. **Improve documentation**

### Development Setup
```bash
git clone https://github.com/mkrd/Flask-Squeeze.git
cd Flask-Squeeze
uv sync
uv run playwright install chromium  # Needed once, for the browser test
just check  # Format, lint, type check and test
```

Start reading at `ResponseSqueezer.after_request` in `flask_squeeze/extension.py`.


License
----------------------------------------------------------------------------------------

MIT License - see [LICENSE](LICENSE) file for details.
