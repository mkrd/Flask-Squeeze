#!/bin/sh
while [ $# -gt 0 ]; do case $1 in

	--run-test-app|-r)
		export FLASK_DEBUG=1
		export PYTHONDONTWRITEBYTECODE=1
		cd tests
		poetry run flask --app "test_app:create_app()" run --host=localhost --port=5000 --debug --reload
		shift ;;


	--test|-t)
		poetry run pytest -p no:cacheprovider --capture=no --cov-report=term-missing --cov=flask_squeeze tests
		shift ;;


	*|-*|--*)
		echo "Unknown option $1"
		exit 2
		exit 1 ;;

esac; done
