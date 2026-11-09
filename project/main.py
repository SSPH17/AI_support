from flask import Flask, render_template

app = Flask(__name__)

@app.route("/")

@app.route("/Projecs")
def projects():
    return render_template("inex.html", title="")

@app.route("/AI-Chat")
def chat():
    return render_template("inex.html", title="")

@app.route("/History")
def history():
    return render_template("inex.html", title="")

@app.route("/Settings")
def settings():
    return render_template("inex.html", title="")


if __name__ == "__main__":
    app.run(debug=True)