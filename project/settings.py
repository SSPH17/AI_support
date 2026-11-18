import os
import json
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify

settings_bp = Blueprint('settings', __name__, template_folder='templates')

CONFIG_FILE = 'config.json'

def get_config():
    """Читает настройки из файла или возвращает дефолтные"""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"ai_model": "gigachat"} # По умолчанию GigaChat

def save_config(config):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

@settings_bp.route("/Settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        new_model = request.form.get("ai_model")
        if new_model in ["gigachat", "deepseek"]:
            config = get_config()
            config["ai_model"] = new_model
            save_config(config)
            
            # Возвращаем JSON, так как запрос идет из JS
            return jsonify({"status": "ok", "model": new_model})
            
        return jsonify({"error": "Неверная модель"}), 400

    config = get_config()
    return render_template("index.html", title="Настройки", current_model=config.get("ai_model", "gigachat"))