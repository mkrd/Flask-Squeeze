from flask import Blueprint

bp = Blueprint("main", __name__, template_folder="templates")
from test_app.main import routes  # noqa: E402, F401
