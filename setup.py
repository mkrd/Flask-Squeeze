"""
Flask-Squeeze
-------------

Automatically minify JS/CSS and crompress all responses with brotli, with caching for static assets.
"""
import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()


setuptools.setup(
    name='Flask-Squeeze',
    version='1.0',
    url='https://github.com/mkrd/flask-squeeze',
    license='MIT License',
    author='Marcel Kröker',
    author_email='kroeker.marcel@gmail.com',
    description='Compress and minify Flask responses!',
    long_description=long_description,
    long_description_content_type="text/markdown",
    packages=setuptools.find_packages(),
    platforms='any',
    install_requires=[
        'Flask',
        'hashlib',
        'brotli',
        'rjsmin',
        'rcssmin',
    ],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        'Intended Audience :: Developers',
        'Programming Language :: Python',
        'Topic :: Software Development :: Libraries :: Python Modules'
    ]
)