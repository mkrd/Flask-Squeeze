set dotenv-load := true

default:
    @just --list # @ suppresses printing the executed command


# MARK: Project


alias o := outdated
outdated:
	uv tree --outdated --depth 1

alias up := upgrade
upgrade:
	uv lock --upgrade
	uv sync

publish:
    uv build
    uv publish
    rm -rf dist


# MARK: Code Quality


ruff-check:
	uv run ruff check .

ruff-format:
	uv run ruff format --check .
	uv run ruff format .

alias r := ruff
ruff:
	@just ruff-check
	@just ruff-format

alias tc := typecheck
typecheck:
	uv run pyrefly check . --no-progress-bar

alias t := test
test:
	uv run coverage run -m unittest discover
	uv run coverage report

alias c := check
check:
	@just ruff
	@just typecheck
	@just test
