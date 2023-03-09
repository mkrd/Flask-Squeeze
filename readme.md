# Flask-Squeeze

[![Downloads](https://pepy.tech/badge/flask-squeeze)](https://pepy.tech/project/flask-squeeze)

Flask-Squeeze is a Flask extension that automatically:
- **Minifies** repsonses with the mimetypes javascript and css
- **Compresses** all HTTP responses with brotli if the browser supports it, or gzip if the browser supports it!
- **Caches** static files so that they don't have to be re-compressed. The cache will be cleared each time Flask restarts. Files are considered to be static if they contain ".../static/..." in their request path.

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
- `COMPRESS_MIN_SIZE (default=500)`: Defines the minimum file size in bytes to activate the compression
- `COMPRESS_MINIFY_CSS (default=True)`: Enable or disable css minification using rcssmin.
- `COMPRESS_MINIFY_JS (default=True)`: Enable or disable css minification using rcssmin.
- `COMPRESS_VERBOSE_LOGGING (default=False)`: Enable or disable verbose logging. If enabled, Flask-Squeeze will print what it does into the terminal in a highlighted color.

### Compression level options

> Static files are chached, so they only have to be compressed once.
> Dynamic files like generated HTML files will not be cached, so they will be compressed for each response.

- `COMPRESS_LEVEL_BROTLI_STATIC (default=11, min=0 , max=11)`: Defines the compression level of brotli for static files.
- `COMPRESS_LEVEL_BROTLI_DYNAMIC (default=1, min=0, max=11)`: Defines the compression level of brotli for dynamic files.
- `COMPRESS_LEVEL_GZIP_STATIC (default=11, min=0 , max=9)`: Defines the compression level of gzip for static files.
- `COMPRESS_LEVEL_GZIP_DYNAMIC (default=1, min=0, max=9)`:  Defines the compression level of gzip for dynamic files.
