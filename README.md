![Logo](https://github.com/mkrd/Flask-Squeeze/blob/master/assets/logo.png?raw=true)

[![Downloads](https://pepy.tech/badge/flask-squeeze)](https://pepy.tech/project/flask-squeeze)
![Tests](https://github.com/mkrd/Flask-Squeeze/actions/workflows/test.yml/badge.svg)
![Coverage](https://github.com/mkrd/Flask-Squeeze/blob/master/assets/coverage.svg?raw=1)

Flask-Squeeze is a Flask extension that automatically:
- **Minifies** responses with JavaScript, CSS, and HTML content
- **Compresses** all responses with brotli (preferred), gzip, or deflate compression based on browser support
- **Protects** against the BREACH exploit by adding random padding to compressed responses
- **Caches** static files so they don't need to be re-compressed, with both in-memory and persistent disk caching options
- **Optimizes performance** with intelligent compression levels for static vs. dynamic content
- **Works out-of-the-box** - no changes needed to your existing Flask routes or templates

Files are considered static if the substring "/static/" is in their request path.


Table of Contents
----------------------------------------------------------------------------------------
- [Compatibility](#compatibility)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Contributing](#contributing)


Compatibility
----------------------------------------------------------------------------------------

- Tested with Python 3.8 to 3.14


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

    # Init all other extensions
    # AFTER Flask-Squeeze

    return app
```

Thats it! The responses of your Flask app will now get minified and compressed, if the browser supports it.
To control how Flask-Squeeze behaves, the following options exist:


### Basic Options
| Option | Default | Description |
| --- | --- | --- |
| `SQUEEZE_COMPRESS` | `True` | Enable/disable compression |
| `SQUEEZE_MIN_SIZE` | `500` | Minimum file size (bytes) to compress |
| `SQUEEZE_CACHE_DIR` | `None` | Directory for persistent cache (`None` = in-memory only) |
| `SQUEEZE_VERBOSE_LOGGING` | `False` | Enable debug output |

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

### Example Configuration
```python
app.config.update({
    'SQUEEZE_CACHE_DIR': './cache/flask_squeeze/',  # Enable persistent caching
    'SQUEEZE_MIN_SIZE': 1000,  # Only compress files > 1KB
    'SQUEEZE_VERBOSE_LOGGING': True,  # Debug mode
})
```


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
just test  # Run tests
just run-test-app  # Run test app
```


License
----------------------------------------------------------------------------------------

MIT License - see [LICENSE](LICENSE) file for details.
