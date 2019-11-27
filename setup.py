"""
Flask-Squeeze
-------------

Automatically minify JS/CSS and crompress all responses with brotli, with caching for static assets
"""
from setuptools import setup


setup(
    name='Flask-Squeeze',
    version='1.0',
    url='https://github.com/mkrd/flask-squeeze',
    license='MIT License',
    author='Marcel Kröker',
    author_email='kroeker.marcel@gmail.com',
    description='Very short description',
    long_description=__doc__,
    py_modules=['flask_squeeze'],
    # if you would be using a package instead use packages instead
    # of py_modules:
    # packages=['flask_sqlite3'],
    zip_safe=False,
    include_package_data=True,
    platforms='any',
    install_requires=[
        'Flask'
    ],
    classifiers=[
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Topic :: Internet :: WWW/HTTP :: Dynamic Content',
        'Topic :: Software Development :: Libraries :: Python Modules'
    ]
)