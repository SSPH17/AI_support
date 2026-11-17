import os
import json
import uuid
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, jsonify

history_bp = Blueprint('history', __name__, template_folder='templates')

HISTORY_DIR = 'chat_history'
os.makedirs(HISTORY_DIR, exist_ok=True)

# Создаем папку для историй при запуске
os.makedirs(HISTORY_DIR, exist_ok=True)

@history_bp.route("/History")
def history():
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
                })
    
    # Сортируем по дате (новые сверху)
    chats.sort(key=lambda x: x["date"], reverse=True)
    chats = chats[:30]  # показываем только 30 последних

    return render_template("index.html", title="История", chat_history=chats)

@history_bp.route("/api/save_chat", methods=["POST"])
def save_chat():
    try:
        data = request.get_json()
        chat_id = data.get("id")
        messages = data.get("messages", [])
        
        if not chat_id:
            chat_id = str(uuid.uuid4())[:8]
        
        # Формируем имя чата по первому сообщению пользователя
        title = "Новый чат"
        for msg in messages:
            if msg.get("role") == "user":
                title = msg.get("content", "")[:30] + "..."
                break

        chat_data = {
            "id": chat_id,
            "title": title,
            "date": datetime.now().strftime("%d.%m.%Y %H:%M"),
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
def load_chat(chat_id):
    file_path = os.path.join(HISTORY_DIR, f"{chat_id}.json")
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            return jsonify(json.load(f))
    return jsonify({"error": "Чат не найден"}), 404

@history_bp.route("/api/delete_chat/<chat_id>", methods=["POST"])
def delete_chat(chat_id):
    file_path = os.path.join(HISTORY_DIR, f"{chat_id}.json")
    if os.path.exists(file_path):
        os.remove(file_path)
        return jsonify({"status": "ok"})
    return jsonify({"error": "Чат не найден"}), 404

def cleanup_old_chats(days=20):
    """Удаляет чаты старше N дней."""
    if not os.path.exists(HISTORY_DIR):
        return
    cutoff = datetime.now() - timedelta(days=days)
    for filename in os.listdir(HISTORY_DIR):
        if not filename.endswith(".json"):
            continue
        file_path = os.path.join(HISTORY_DIR, filename)
        try:
            # Проверяем дату изменения файла (проще, чем парсить содержимое)
            mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
            if mtime < cutoff:
                os.remove(file_path)
        except Exception:
            pass