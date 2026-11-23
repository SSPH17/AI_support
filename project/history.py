import os
import json
import uuid
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, jsonify

from auth import login_required, current_user, get_user_role

history_bp = Blueprint('history', __name__, template_folder='templates')

HISTORY_DIR = 'chat_history'
os.makedirs(HISTORY_DIR, exist_ok=True)


@history_bp.route("/History")
@login_required
def history():
    username = current_user()
    cleanup_old_chats(days=20)
    chats = []
    for filename in os.listdir(HISTORY_DIR):
        if filename.endswith(".json"):
            file_path = os.path.join(HISTORY_DIR, filename)
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                chats.append({
                    "id": data.get("id"),
                    "title": data.get("title", "Без названия"),
                    "date": data.get("date", ""),
                    "owner": data.get("owner"),
                })

    # Сначала сортируем (по строке даты — как было, но лучше по mtime)
    chats.sort(key=lambda x: x["date"], reverse=True)

    # Фильтр по владельцу (админ видит всё)
    if get_user_role(username) != "admin":
        chats = [c for c in chats if c.get("owner") == username]

    chats = chats[:30]

    return render_template("index.html", title="История", chat_history=chats)


@history_bp.route("/api/save_chat", methods=["POST"])
@login_required
def save_chat():
    try:
        data = request.get_json()
        chat_id = data.get("id")
        messages = data.get("messages", [])

        if not chat_id:
            chat_id = str(uuid.uuid4())[:8]

        title = "Новый чат"
        for msg in messages:
            if msg.get("role") == "user":
                title = msg.get("content", "")[:30] + "..."
                break

        chat_data = {
            "id": chat_id,
            "title": title,
            "date": datetime.now().strftime("%d.%m.%Y %H:%M"),
            "owner": current_user(),
            "messages": messages
        }

        file_path = os.path.join(HISTORY_DIR, f"{chat_id}.json")
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(chat_data, f, ensure_ascii=False, indent=2)

        return jsonify({"status": "ok", "id": chat_id})

    except Exception as e:
        print(f"ОШИБКА СОХРАНЕНИЯ ЧАТА: {e}")
        return jsonify({"error": str(e)}), 500


@history_bp.route("/api/load_chat/<chat_id>", methods=["GET"])
@login_required
def load_chat(chat_id):
    file_path = os.path.join(HISTORY_DIR, f"{chat_id}.json")
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        owner = data.get("owner")
        if owner and owner != current_user() and get_user_role(current_user()) != "admin":
            return jsonify({"error": "Нет доступа"}), 403
        return jsonify(data)
    return jsonify({"error": "Чат не найден"}), 404


@history_bp.route("/api/delete_chat/<chat_id>", methods=["POST"])
@login_required
def delete_chat(chat_id):
    file_path = os.path.join(HISTORY_DIR, f"{chat_id}.json")
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        owner = data.get("owner")
        if owner and owner != current_user() and get_user_role(current_user()) != "admin":
            return jsonify({"error": "Нет доступа"}), 403
        os.remove(file_path)
        return jsonify({"status": "ok"})
    return jsonify({"error": "Чат не найден"}), 404


def cleanup_old_chats(days=20):
    if not os.path.exists(HISTORY_DIR):
        return
    cutoff = datetime.now() - timedelta(days=days)
    for filename in os.listdir(HISTORY_DIR):
        if not filename.endswith(".json"):
            continue
        file_path = os.path.join(HISTORY_DIR, filename)
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
            if mtime < cutoff:
                os.remove(file_path)
        except Exception:
            pass