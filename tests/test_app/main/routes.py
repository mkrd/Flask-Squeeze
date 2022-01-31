# Flask
from flask import (
	render_template,
	flash,
	url_for,
	redirect,
	abort,
	send_file,
	current_app,
)

from datetime import datetime

# Blueprint setup
from test_app.main import bp


@bp.route("/")
@bp.route("/index")
def hello():
	data = datetime.utcnow()
	return render_template("index.html", data=str(data))
