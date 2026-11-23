import os
import sys
import io
from dotenv import load_dotenv
load_dotenv()

from flask import Flask, render_template
from projects import projects_bp
from AI_chat import ai_chat_bp
from history import history_bp, cleanup_old_chats
from settings import settings_bp
from auth import auth_bp, current_user

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

app = Flask(__name__)
app.secret_key = 'super_secret_key'
app.config['MAX_CONTENT_LENGTH'] = 512 * 1024 * 1024

# Создаем папки при запуске
os.makedirs('uploads', exist_ok=True)
os.makedirs('.temp_uploads', exist_ok=True)
os.makedirs('chat_history', exist_ok=True)

# Очищаем старые чаты
cleanup_old_chats(days=20)

# Регистрируем блюпринты
app.register_blueprint(auth_bp)
app.register_blueprint(projects_bp)
app.register_blueprint(ai_chat_bp)
app.register_blueprint(history_bp)
app.register_blueprint(settings_bp)


@app.context_processor
def inject_user():
    return {"current_user": current_user()}


# Обработчик ошибки 413 (слишком большой файл)
@app.errorhandler(413)
def request_entity_too_large(error):
    from flask import flash, redirect, url_for
    flash("Ошибка: размер файла превышает 0.5 ГБ (512 МБ).")
    return redirect(url_for("projects.projects"))


# Главная страница (корень сайта)
@app.route("/")
def home():
    return render_template("index.html", title="Главная")


if __name__ == "__main__":
    app.run(debug=True)