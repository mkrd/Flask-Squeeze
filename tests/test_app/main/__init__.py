# flake8: noqa
from flask import Blueprint

bp = Blueprint("main", __name__, template_folder="templates")
from test_app.main import routes
