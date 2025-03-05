from __future__ import annotations

from flask import Flask

from flask_squeeze import Squeeze


def create_app(update_config: dict | None = None) -> Flask:
	squeeze = Squeeze()
	app = Flask(__name__, instance_relative_config=True)
	app.config.from_mapping(
		{
			"ENV": "development",
			"DEBUG": True,
			"SECRET_KEY": "dev",
			"SQUEEZE_MIN_SIZE": 0,
			"SQUEEZE_VERBOSE_LOGGING": True,
		}
		| (update_config or {}),
	)

	squeeze.init_app(app)

	from test_app import main

	app.register_blueprint(main.bp)

	return app
