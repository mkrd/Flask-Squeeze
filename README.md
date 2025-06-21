![Logo](https://github.com/mkrd/Flask-Squeeze/blob/master/assets/logo.png?raw=true)

[![Downloads](https://pepy.tech/badge/flask-squeeze)](https://pepy.tech/project/flask-squeeze)
![Tests](https://github.com/mkrd/Flask-Squeeze/actions/workflows/test.yml/badge.svg)
![Coverage](https://github.com/mkrd/Flask-Squeeze/blob/master/assets/coverage.svg?raw=1)

Flask-Squeeze is a Flask extension that automatically:
- **Minifies** responses with the mimetypes javascript and css
- **Compresses** all responses with brotli if the browser supports it, or gzip if the browser supports it!
- **Protects** against the BREACH exploit
- **Caches** static files so that they don't have to be re-compressed. By default, the cache is in-memory and will be cleared each time Flask restarts. With persistent caching enabled, compressed responses are saved to disk and survive server restarts.
- **Persistent caching** (optional) saves compressed static files to disk, improving startup times and reducing CPU usage across server restarts

Files are considered static if the substring "/static/" is in their request path.

## Compatibility
- Tested with Python 3.8, 3.9, 3.10, 3.11, 3.12 and 3.13

## Installation
```
pip install Flask-Squeeze
```

## Usage
Initialize Flask-Squeeze **BEFORE** all other extensions and after_request handlers! Flask executes after_request handlers in reverse order of declaration, and the compression should be the last step before sending the response.
```python
from flask_squeeze import Squeeze
squeeze = Squeeze()

def create_app():
    app = Flask(__name__)

    # Init Flask-Squeeze
    squeeze.init_app(app)

    # Init all other extensions
    # AFTER Flask-Squeeze

    return app
```

Thats it! The responses of your Flask app will now get minified and compressed, if the browser supports it.
To control how Flask-Squeeze behaves, the following options exist:

### General options
You can configure Flask-Squeeze with the following options in your [Flask config](https://flask.palletsprojects.com/en/latest/config/):

| Option | Default | Description |
| --- | --- | --- |
| `SQUEEZE_COMPRESS` | `True` | Enables or disables compression |
| `SQUEEZE_MIN_SIZE` | `500` | Defines the minimum file size in bytes to activate the compression |
| `SQUEEZE_CACHE_DIR` | `None` | Directory to store persistent cache files. If `None`, only in-memory caching is used |
| `SQUEEZE_VERBOSE_LOGGING` | `False` | Enable or disable verbose logging. If enabled, Flask-Squeeze will print what it does into the terminal in a highlighted color |

### Persistent Caching
Flask-Squeeze supports persistent caching of compressed static files. When enabled, compressed responses are saved to disk and reloaded on server restart, eliminating the need to recompress unchanged files.

```python
app.config['SQUEEZE_CACHE_DIR'] = './cache/flask_squeeze/'  # Enable persistent caching
```

Benefits:
- **Faster server startup**: No need to recompress static files on restart
- **Reduced CPU usage**: Avoid redundant compression operations
- **Consistent performance**: Immediate cache hits after restart

Cache files are automatically managed:
- Cache entries are validated using file content hashes
- Stale cache entries are automatically replaced when files change
- Use `squeeze.clear_cache()` to manually clear the cache

#### Cache Management
```python
from flask_squeeze import Squeeze

squeeze = Squeeze(app)

# Clear all cached files (memory and disk)
squeeze.clear_cache()
```

### Minification options
| Option | Default | Description |
| --- | --- | --- |
| `SQUEEZE_MINIFY_CSS` | `True` | Enable or disable css minification using rcssmin |
| `SQUEEZE_MINIFY_JS` | `True` | Enable or disable js minification using rjsmin |

### Compression level options
> Static files are cached, so they only have to be compressed once (and are persisted to disk if `SQUEEZE_CACHE_DIR` is configured).
> Dynamic files like generated HTML files will not be cached, so they will be compressed for each response.

| Option | Default | Description |
| --- | --- | --- |
| `SQUEEZE_LEVEL_BROTLI_STATIC` | `default=11, min=0 , max=11` | Defines the compression level of brotli for static files |
| `SQUEEZE_LEVEL_BROTLI_DYNAMIC` | `default=1, min=0, max=11` | Defines the compression level of brotli for dynamic files |
| `SQUEEZE_LEVEL_DEFLATE_STATIC` | `default=9, min=-1 , max=9` | Defines the compression level of deflate for static files |
| `SQUEEZE_LEVEL_DEFLATE_DYNAMIC` | `default=1, min=-1, max=9` |  Defines the compression level of deflate for dynamic files |
| `SQUEEZE_LEVEL_GZIP_STATIC` | `default=9, min=0 , max=9` | Defines the compression level of gzip for static files |
| `SQUEEZE_LEVEL_GZIP_DYNAMIC` | `default=1, min=0, max=9` |  Defines the compression level of gzip for dynamic files |
