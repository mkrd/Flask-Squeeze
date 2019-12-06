# Start me with "python3 app.py"

import sys
import os
sys.path.append(os.path.dirname(sys.path[0]))

from datetime import datetime

from flask import Flask, render_template, url_for
app = Flask(__name__)
app.config["ENV"] = "development"
app.config["DEBUG"] = True



from flask_squeeze import Squeeze
squeeze = Squeeze()
squeeze.init_app(app)
app.config["COMPRESS_MIN_SIZE"] = 0
app.config["COMPRESS_VERBOSE_LOGGING"] = True

@app.route("/")
@app.route("/index")
def hello():
    data = datetime.utcnow()
    return render_template("index.html", data=str(data))

if __name__ == "__main__":
    app.run()