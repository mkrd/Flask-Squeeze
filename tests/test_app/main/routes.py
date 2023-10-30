from datetime import datetime, timezone

# Flask
from flask import (
	render_template,
)

# Blueprint setup
from test_app.main import bp


@bp.route("/")
@bp.route("/index")
def hello() -> str:
	data = datetime.now(timezone.utc)
	return render_template("index.html", data=str(data))
