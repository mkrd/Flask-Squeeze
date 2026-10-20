set dotenv-load := true

default:
    @just --list # @ suppresses printing the executed command


##########################################################################################
#### MARK: uv
#### (synced from ~/.config/just)


alias o := outdated
outdated:
	uv tree --outdated --depth 1


alias up := upgrade
upgrade:
	uv lock --upgrade
	uv sync


##########################################################################################
#### MARK: Linting
#### (synced from ~/.config/just)


ruff-fix:
	uv run ruff check . --fix


ruff-format:
	uv run ruff format .


alias r := ruff
ruff:
	@just ruff-fix
	@just ruff-format


alias tc := typecheck
typecheck:
	uv run pyrefly check . --no-progress-bar


# Lint without modifying files, for CI.
ruff-check:
	uv run ruff check .


# Check formatting without modifying files, for CI.
ruff-format-check:
	uv run ruff format --check .


##########################################################################################
#### MARK: Testing
#### (synced from ~/.config/just)


alias t := test
test:
	uv run coverage run -m unittest discover
	uv run coverage report

alias c := check
check:
	@just ruff
	@just typecheck
	@just test


##########################################################################################
#### MARK: Publish
#### (synced from ~/.config/just)


publish:
	uv build
	uv publish
	rm -rf dist


