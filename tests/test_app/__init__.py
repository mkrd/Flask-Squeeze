from __future__ import annotations

from flask import Flask

from flask_squeeze import Squeeze


def create_app(update_config: dict[str, str] | None = None) -> Flask:
	squeeze = Squeeze()
	app = Flask(__name__, instance_relative_config=True)
	config = {
		"ENV": "development",
		"DEBUG": True,
		"SECRET_KEY": "dev",
		"SQUEEZE_MIN_SIZE": 0,
		"SQUEEZE_VERBOSE_LOGGING": True,
	}
	if update_config:
		config.update(update_config)
	app.config.from_mapping(config)

	squeeze.init_app(app)

	from test_app import main

	app.register_blueprint(main.bp)

	return app
