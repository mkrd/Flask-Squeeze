poetry install
pytest --capture=no --cov-report=term-missing --cov=flask_squeeze tests
