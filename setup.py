"""
Flask-Squeeze
-------------

Automatically minify JS/CSS and crompress all responses with brotli, with caching for static assets.
"""

# How to publish:
# python3 setup.py sdist bdist_wheel
# python3 -m twine upload dist/*

import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="Flask-Squeeze",
    version="1.7",
    url="https://github.com/mkrd/flask-squeeze",
    license="MIT License",
    author="Marcel Kröker",
    author_email="kroeker.marcel@gmail.com",
    description="Compress and minify Flask responses!",
    long_description=long_description,
    long_description_content_type="text/markdown",
    py_modules=["flask_squeeze"],
    packages=setuptools.find_packages(),
    include_package_data=True,
    platforms="any",
    install_requires=[  
        "flask",
        "brotli",
        "rjsmin",
        "rcssmin",
        "termcolor",
    ],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Intended Audience :: Developers",
        "Programming Language :: Python",
        "Topic :: Software Development :: Libraries :: Python Modules"
    ]
)