import os
import json
import uuid
import shutil
import time
import threading
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'super_secret_key'

# Ограницение по размеру файлов
app.config['MAX_CONTENT_LENGTH'] = 512 * 1024 * 1024

@app.errorhandler(413)
def request_entity_too_large(error):
    flash("Ошибка: размер файла превышает 0.5 ГБ (512 МБ).")
    return redirect(request.referrer or url_for("projects"))

# Загрузчик файлов
UPLOAD_FOLDER = 'uploads'
TEMP_FOLDER = '.temp_uploads'
STATUS_FILE = 'statuses.json'
ALLOWED_EXTENSIONS = {'.md', '.markdown', '.txt'}
VALID_STATUSES = [
    "Ожидает обработки",
    "Обрабатывается",
    "Готов к поиску",
    "Ошибка обработки"
]

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(TEMP_FOLDER, exist_ok=True)

status_lock = threading.Lock()


def is_allowed_file(filename):
    ext = os.path.splitext(filename)[1].lower()
    return ext in ALLOWED_EXTENSIONS


def is_safe_subpath(subpath):
    base = os.path.abspath(app.config['UPLOAD_FOLDER'])
    target = os.path.abspath(os.path.join(base, subpath))
    return target == base or target.startswith(base + os.sep)


def get_unique_filename(directory, filename):
    name, ext = os.path.splitext(filename)
    counter = 1
    new_filename = filename
    while os.path.exists(os.path.join(directory, new_filename)):
        new_filename = f"{name} ({counter}){ext}"
        counter += 1
    return new_filename


def get_statuses():
    with status_lock:
        if os.path.exists(STATUS_FILE):
            with open(STATUS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}


def save_status(rel_path, status_text):
    with status_lock:
        statuses = {}
        if os.path.exists(STATUS_FILE):
            with open(STATUS_FILE, 'r', encoding='utf-8') as f:
                statuses = json.load(f)
        statuses[rel_path] = status_text
        with open(STATUS_FILE, 'w', encoding='utf-8') as f:
            json.dump(statuses, f, ensure_ascii=False, indent=2)


def delete_status(rel_path):
    with status_lock:
        if os.path.exists(STATUS_FILE):
            with open(STATUS_FILE, 'r', encoding='utf-8') as f:
                statuses = json.load(f)
            if rel_path in statuses:
                del statuses[rel_path]
                with open(STATUS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(statuses, f, ensure_ascii=False, indent=2)

def delete_folder_statuses(folder_rel_path):
    """Удаляет статусы всех файлов, находившихся внутри удалённой папки."""
    prefix = folder_rel_path.rstrip("/") + "/"
    with status_lock:
        if os.path.exists(STATUS_FILE):
            with open(STATUS_FILE, 'r', encoding='utf-8') as f:
                statuses = json.load(f)
            updated_statuses = {
                k: v for k, v in statuses.items()
                if not k.startswith(prefix)
            }
            if len(updated_statuses) != len(statuses):
                with open(STATUS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(updated_statuses, f, ensure_ascii=False, indent=2)

def process_file_in_background(full_path, rel_path):
    """Автоматическая фоновая обработка файла системой."""
    try:
        # 1. Имитация очереди перед началом работы
        time.sleep(2)
        if not os.path.exists(full_path):
            return
        save_status(rel_path, "Обрабатывается")

        # 2. Проверка содержимого файла
        time.sleep(3)
        if not os.path.exists(full_path):
            return

        if os.path.getsize(full_path) == 0:
            save_status(rel_path, "Ошибка обработки")
            return

        with open(full_path, 'r', encoding='utf-8') as f:
            _ = f.read(1024)

        save_status(rel_path, "Готов к поиску")
    except Exception:
        if os.path.exists(full_path):
            save_status(rel_path, "Ошибка обработки")


def start_file_processing(full_path, rel_path):
    save_status(rel_path, "Ожидает обработки")
    thread = threading.Thread(
        target=process_file_in_background,
        args=(full_path, rel_path),
        daemon=True
    )
    thread.start()


def format_size(bytes_size):
    for unit in ['Б', 'КБ', 'МБ']:
        if bytes_size < 1024:
            return f"{bytes_size:.1f} {unit}" if unit != 'Б' else f"{bytes_size} Б"
        bytes_size /= 1024
    return f"{bytes_size:.2f} ГБ"


### ДОМАШНЯЯ СТРАНИЦА ###
@app.route("/")
def home():
    return render_template("index.html", title="Главная")


### СТРАНИЦА ПРОЕКТОВ ###
@app.route("/Projects", methods=["GET", "POST"])
def projects():
    current_folder = request.args.get("folder", "").strip("/\\")
    if not is_safe_subpath(current_folder):
        current_folder = ""

    target_dir = os.path.join(app.config["UPLOAD_FOLDER"], current_folder)
    os.makedirs(target_dir, exist_ok=True)

    if request.method == "POST":
        action = request.form.get("action")

        # 1. Создание новой папки
        if action == "create_folder":
            folder_name = os.path.basename(request.form.get("folder_name", "").strip())
            if folder_name and folder_name not in (".", ".."):
                os.makedirs(os.path.join(target_dir, folder_name), exist_ok=True)

        # 2. Первичная загрузка файла
        elif action == "upload_file" and "file" in request.files:
            file = request.files["file"]
            if file.filename != "":
                filename = os.path.basename(file.filename.strip())
                if not is_allowed_file(filename):
                    flash("Ошибка: разрешены только форматы .md, .markdown и .txt", "error")
                else:
                    dest_path = os.path.join(target_dir, filename)
                    if os.path.exists(dest_path):
                        temp_id = str(uuid.uuid4())
                        file.save(os.path.join(TEMP_FOLDER, temp_id))
                        return redirect(url_for(
                            "projects",
                            folder=current_folder,
                            conflict_file=filename,
                            temp_id=temp_id
                        ))
                    else:
                        file.save(dest_path)
                        rel_path = os.path.join(current_folder, filename).replace("\\", "/")
                        start_file_processing(dest_path, rel_path)
                        flash(f"Файл «{filename}» загружен и отправлен в обработку.", "success")

        # 3. Разрешение конфликта имён (Заменить / Сохранить отдельно / Отмена)
        elif action == "resolve_conflict":
            choice = request.form.get("choice")
            temp_id = os.path.basename(request.form.get("temp_id", ""))
            orig_filename = os.path.basename(request.form.get("filename", ""))
            temp_path = os.path.join(TEMP_FOLDER, temp_id)

            if os.path.isfile(temp_path) and orig_filename and is_allowed_file(orig_filename):
                if choice == "replace":
                    dest_path = os.path.join(target_dir, orig_filename)
                    shutil.move(temp_path, dest_path)
                    rel_path = os.path.join(current_folder, orig_filename).replace("\\", "/")
                    start_file_processing(dest_path, rel_path)
                    flash(f"Файл «{orig_filename}» обновлён и отправлен в обработку.", "success")

                elif choice == "keep_both":
                    new_filename = get_unique_filename(target_dir, orig_filename)
                    dest_path = os.path.join(target_dir, new_filename)
                    shutil.move(temp_path, dest_path)
                    rel_path = os.path.join(current_folder, new_filename).replace("\\", "/")
                    start_file_processing(dest_path, rel_path)
                    flash(f"Файл сохранён как «{new_filename}» и отправлен в обработку.", "success")

                else:
                    os.remove(temp_path)
                    flash("Загрузка отменена.", "error")

        # 4. Удаление файла
        elif action == "delete_file":
            filename = os.path.basename(request.form.get("filename", ""))
            file_path = os.path.join(target_dir, filename)
            if filename and is_safe_subpath(os.path.join(current_folder, filename)) and os.path.isfile(file_path):
                os.remove(file_path)
                rel_path = os.path.join(current_folder, filename).replace("\\", "/")
                delete_status(rel_path)
                flash(f"Файл «{filename}» удалён.", "success")

        # 5. Удаление папки (пустой или с содержимым)
        elif action == "delete_folder":
            folder_name = os.path.basename(request.form.get("folder_name", ""))
            folder_subpath = os.path.join(current_folder, folder_name)
            folder_path = os.path.join(target_dir, folder_name)

            if folder_name and is_safe_subpath(folder_subpath) and os.path.isdir(folder_path):
                shutil.rmtree(folder_path)
                rel_path = folder_subpath.replace("\\", "/")
                delete_folder_statuses(rel_path)
                flash(f"Папка «{folder_name}» удалена.", "success")

        return redirect(url_for("projects", folder=current_folder))

        

    # Проверка активного конфликта загрузки
    conflict_file = os.path.basename(request.args.get("conflict_file", ""))
    temp_id = os.path.basename(request.args.get("temp_id", ""))
    conflict_data = None
    if conflict_file and temp_id and os.path.isfile(os.path.join(TEMP_FOLDER, temp_id)):
        conflict_data = {"filename": conflict_file, "temp_id": temp_id}

    # Режим только просмотра файла (?view=имя_файла)
    view_filename = os.path.basename(request.args.get("view", ""))
    viewed_file = None
    if view_filename:
        view_path = os.path.join(target_dir, view_filename)
        if is_safe_subpath(os.path.join(current_folder, view_filename)) and os.path.isfile(view_path):
            try:
                with open(view_path, "r", encoding="utf-8") as f:
                    file_content = f.read()
            except UnicodeDecodeError:
                with open(view_path, "r", encoding="cp1251", errors="replace") as f:
                    file_content = f.read()
            viewed_file = {"name": view_filename, "content": file_content}

    # Сбор списка папок и файлов
    folders = []
    files = []
    statuses = get_statuses()

    for item in os.listdir(target_dir):
        full_path = os.path.join(target_dir, item)
        rel_path = os.path.join(current_folder, item).replace("\\", "/")

        if os.path.isdir(full_path):
            is_empty = len(os.listdir(full_path)) == 0
            folders.append({
                "name": item,
                "path": rel_path,
                "is_empty": is_empty
            })
        elif is_allowed_file(item):
            stats = os.stat(full_path)
            files.append({
                "name": item,
                "size": format_size(stats.st_size),
                "date": datetime.fromtimestamp(stats.st_mtime).strftime("%d.%m.%Y %H:%M"),
                "status": statuses.get(rel_path, "Ожидает обработки")
            })

    parent_folder = os.path.dirname(current_folder).replace("\\", "/") if current_folder else None

    return render_template(
        "index.html",
        title="Проекты",
        folders=folders,
        files=files,
        current_folder=current_folder,
        parent_folder=parent_folder,
        valid_statuses=VALID_STATUSES,
        viewed_file=viewed_file,
        conflict_data=conflict_data
    )

### СТРАНИЦА ЧАТА С ИИ ###
@app.route("/AI-Chat")
def chat():
    return render_template("index.html", title="AI-чат")


### СТРАНИЦА ИСТОРИИ ЧАТОВ ###
@app.route("/History")
def history():
    return render_template("index.html", title="История")


### НАСТРОЙКИ ###
@app.route("/Settings")
def settings():
    return render_template("index.html", title="Настройки")


if __name__ == "__main__":
    app.run(debug=True)