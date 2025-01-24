set dotenv-load := true

# @ means: surpress printing the executed command

default:
    @just --list

alias r := run-test-app

# Run test app
run-test-app:
    export FLASK_DEBUG=1
    export PYTHONDONTWRITEBYTECODE=1
    cd tests && uv run flask --app "test_app:create_app()" run --host=localhost --port=5000 --debug --reload


alias t := test

# Run tests
test:
	uv run pytest -p no:cacheprovider --capture=no --cov-report=term-missing --cov=flask_squeeze tests


publish:
    uv build
    uv publish
    rm -rf dist
    rm -rf flask_squeeze.egg-info

