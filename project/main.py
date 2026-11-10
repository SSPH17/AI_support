from flask import Flask, render_template

app = Flask(__name__)
@app.route("/")
def home():
    return render_template("index.html", title="Главная")

@app.route("/Projects")
def projects():
    return render_template("index.html", title="Проекты")

@app.route("/AI-Chat")
def chat():
    return render_template("index.html", title="AI-чат")

@app.route("/History")
def history():
    return render_template("index.html", title="История")

@app.route("/Settings")
def settings():
    return render_template("index.html", title="Настройки")


if __name__ == "__main__":
    app.run(debug=True)