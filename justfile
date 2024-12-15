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



# CONTENT    := justfile_directory() + "/content"
# DEPLOY     := justfile_directory() + "/deploy"
# COMMIT_TAG := `date "+%Y-%m-%dT%H:%M:%S"`

# # This list of available targets
# default:
#     @just --list

# # Build local content and deploy to public github repo.
# deploy: build push

# # Build local content to public directory.
# build:
# 	@echo "Generating site..."
# 	@cd {{CONTENT}} && hugo --quiet --minify --gc --cleanDestinationDir --destination {{DEPLOY}}
# 	@cp {{CONTENT}}/CNAME {{DEPLOY}}
# 	@echo "Done"

# # Commit current version of local public directory and push to github.
# push:
# 	@echo "Committing and pushing to github..."
# 	@cd {{DEPLOY}} && git add --all .
# 	@cd {{DEPLOY}} && git commit -m "{{COMMIT_TAG}}"
# 	@cd {{DEPLOY}} && git push -u origin main

# # Run a local server (including drafts).
# server:
# 	@cd {{CONTENT}} && hugo server --buildDrafts
