# Flask-Squeeze

[![Downloads](https://pepy.tech/badge/flask-squeeze)](https://pepy.tech/project/flask-squeeze)

Flask-Squeeze is a Flask extension that automatically:
- Minifies JS and CSS responses.
- Compresses all HTTP responses with brotli if the browser supports it, or gzip if the browser supports it.
- Caches static files so that they don't have to be re-compressed. The cache will be cleared each time Flask restarts! Files are considered to be static if they are contained in a directory that is named "static" (Or generally, if they contain "/static/" in their request path.

## Installation
```
pip3 install Flask-Squeeze
```

## Usage
```python
from flask_squeeze import Squeeze
squeeze = Squeeze()

# Initialize Extension
squeeze.init_app(app)
```

Thats all!

## Options
You can configure Flask-Squeeze with the following options in your [Flask config](https://flask.palletsprojects.com/en/latest/config/):
- `COMPRESS_FLAG (default=True)`: Globally enables or disables Flask-Squeeze
- `COMPRESS_MIN_SIZE (default=500)`: Defines the minimum file size in bytes to activate the brotli compression
- `COMPRESS_LEVEL_STATIC (default=9)`: Possible value are 0 (lowest) to 9 (highest). Defines the compression level of brotli for files in static folders. Theses files fill also be cached, so that they only have to be compressed once.
- `COMPRESS_LEVEL_DYNAMIC (default=5)`: Possible value are 0 (lowest) to 9 (highest). Defines the compression level of brotli for dynamic files like generated HTML files. Theses files will not be cached, so they will be compressed for each response.
- `COMPRESS_MINIFY_CSS (default=True)`: Enable or disable css minification using rcssmin.
- `COMPRESS_MINIFY_JS (default=True)`: Enable or disable css minification using rcssmin.

- `COMPRESS_VERBOSE_LOGGING (default=False)`: Enable or disable verbose logging. If enabled, Flask-Squeeze will print what it does into the terminal in a highlighted color.
