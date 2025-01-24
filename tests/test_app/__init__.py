from flask import Flask

from flask_squeeze import Squeeze


def create_app() -> Flask:
	squeeze = Squeeze()
	app = Flask(__name__, instance_relative_config=True)
	app.config.from_mapping(
		ENV="development",
		DEBUG=True,
		SECRET_KEY="dev",  # noqa: S106
		SQUEEZE_MIN_SIZE=0,
		SQUEEZE_VERBOSE_LOGGING=True,
		SQUEEZE_ADD_DEBUG_HEADERS=True,
	)

	squeeze.init_app(app)

	from test_app import main

	app.register_blueprint(main.bp)

	return app
