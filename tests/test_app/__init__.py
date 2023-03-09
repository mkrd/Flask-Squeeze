from flask import Flask
from flask_squeeze import Squeeze



squeeze = Squeeze()



def create_app(test_config=None):
	"""Create and configure an instance of the Flask application."""
	app = Flask(__name__, instance_relative_config=True)
	app.config.from_mapping(
		ENV="development",
		DEBUG=True,
		SECRET_KEY="dev",
		COMPRESS_MIN_SIZE=0,
		COMPRESS_VERBOSE_LOGGING=True,
		COMPRESS_MINIFY_JS=True,
	)

	squeeze.init_app(app)

	from test_app import main
	app.register_blueprint(main.bp)


	return app
