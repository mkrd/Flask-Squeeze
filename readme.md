# Flask-Squeeze

Flask-Squeeze is a Flask extension that automatically:
- Minifies your JS and CSS files.
- Compresses all HTTP responses with brotli.
- Caches static files so that they don't have to be re-compressed. The cache will be cleared each time Flask restarts! Files are considered to be static if they are contained in a directory that is named "static" (Or generally, if they contain the word "static" in their file path.

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
You can configure Flask-Squeeze with the following options in your Flask config:
- `COMPRESS_FLAG (default=True)`: Globally enables or disables Flask-Squeeze
- `COMPRESS_MIN_SIZE (default=500)`: Defines the minimum file size in bytes to activate the brotli compression
- `COMPRESS_LEVEL_STATIC (default=11)`: Possible value are 0 (lowest) to 11 (highest). Defines the compression level of brotli for files in static folders. Theses files fill also be cached, so that they only have to be compressed once. 
- `COMPRESS_LEVEL_DYNAMIC (default=5)`: Possible value are 0 (lowest) to 11 (highest). Defines the compression level of brotli for dynamic files like generated HTML files. Theses files will not be cached, so they will be compressed for each response.
