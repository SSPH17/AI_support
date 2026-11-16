import os
import json
import uuid
import shutil
import time
import threading
from datetime import datetime
from werkzeug.utils import secure_filename
from flask import Blueprint, render_template, request, redirect, url_for, flash

# Настройки (можно вынести в конфиг, но пока оставим тут)
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

# Создаем Blueprint
projects_bp = Blueprint('projects', __name__, template_folder='templates')

# --- Вспомогательные функции ---

def safe_filename(filename):
    filename = os.path.basename(filename.strip())
    filename = "".join(c for c in filename if c.isprintable() and c not in r'\/:*?"<>|')
    return filename

def is_allowed_file(filename):
    ext = os.path.splitext(filename)[1].lower()
    return ext in ALLOWED_EXTENSIONS

def is_safe_subpath(subpath):
    base = os.path.abspath(UPLOAD_FOLDER)
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

# --- Работа со статусами (потокобезопасная) ---
status_lock = threading.Lock()

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
    prefix = folder_rel_path.rstrip("/") + "/"
    with status_lock:
        if os.path.exists(STATUS_FILE):
            with open(STATUS_FILE, 'r', encoding='utf-8') as f:
                statuses = json.load(f)
            updated_statuses = {k: v for k, v in statuses.items() if not k.startswith(prefix)}
            if len(updated_statuses) != len(statuses):
                with open(STATUS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(updated_statuses, f, ensure_ascii=False, indent=2)

# --- Фоновая обработка ---
def process_file_in_background(full_path, rel_path):
    try:
        time.sleep(2)
        if not os.path.exists(full_path): return
        save_status(rel_path, "Обрабатывается")

        time.sleep(3)
        if not os.path.exists(full_path): return

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
    thread = threading.Thread(target=process_file_in_background, args=(full_path, rel_path), daemon=True)
    thread.start()

def format_size(bytes_size):
    for unit in ['Б', 'КБ', 'МБ']:
        if bytes_size < 1024:
            return f"{bytes_size:.1f} {unit}" if unit != 'Б' else f"{bytes_size} Б"
        bytes_size /= 1024
    return f"{bytes_size:.2f} ГБ"

# --- Маршруты ---

@projects_bp.route("/Projects", methods=["GET", "POST"])
def projects():
    current_folder = os.path.normpath(request.args.get("folder", "")).strip("/\\")
    if current_folder == ".":
        current_folder = ""
    if not is_safe_subpath(current_folder):
        current_folder = ""

    target_dir = os.path.join(UPLOAD_FOLDER, current_folder)
    os.makedirs(target_dir, exist_ok=True)

    if request.method == "POST":
        action = request.form.get("action")

        if action == "create_folder":
            folder_name = os.path.basename(request.form.get("folder_name", "").strip())
            if folder_name and folder_name not in (".", ".."):
                os.makedirs(os.path.join(target_dir, folder_name), exist_ok=True)

        elif action == "upload_file":
            uploaded_files = request.files.getlist("files")
            valid_files = [f for f in uploaded_files if f and f.filename]
            
            if not valid_files:
                flash("Не выбрано ни одного файла.", "error")
                return redirect(url_for("projects.projects", folder=current_folder))

            success_count = 0
            conflict_file = None
            temp_id = None
            conflict_subpath = ""

            is_folder_upload = any("/" in f.filename or "\\" in f.filename for f in valid_files)

            if is_folder_upload:
                first_path = valid_files[0].filename.replace("\\", "/")
                root_folder_name = safe_filename(first_path.split("/")[0])
                if root_folder_name:
                    os.makedirs(os.path.join(target_dir, root_folder_name), exist_ok=True)

            for file in valid_files:
                raw_path = file.filename.replace("\\", "/")
                path_parts = [safe_filename(part) for part in raw_path.split("/") if part]
                if not path_parts: continue
                
                filename = path_parts[-1]
                if filename.startswith(".") or filename.lower() in ("thumbs.db", "desktop.ini"): continue
                if not is_allowed_file(filename): continue

                rel_sub_path = os.path.join(*path_parts)
                dest_path = os.path.join(target_dir, rel_sub_path)
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)

                if os.path.exists(dest_path):
                    if not conflict_file:
                        temp_id = str(uuid.uuid4())
                        file.save(os.path.join(TEMP_FOLDER, temp_id))
                        conflict_file = filename
                        conflict_subpath = os.path.dirname(rel_sub_path)
                    continue

                file.save(dest_path)
                full_rel_path = os.path.join(current_folder, rel_sub_path).replace("\\", "/")
                start_file_processing(dest_path, full_rel_path)
                success_count += 1

            if conflict_file:
                return redirect(url_for("projects.projects", folder=current_folder, conflict_file=conflict_file, temp_id=temp_id, conflict_subpath=conflict_subpath))
            elif success_count > 0:
                flash(f"Успешно загружено файлов: {success_count}.", "success")
            else:
                flash("Не найдено подходящих файлов (.md, .markdown, .txt) для загрузки.", "error")

        elif action == "resolve_conflict":
            choice = request.form.get("choice")
            temp_id = os.path.basename(request.form.get("temp_id", ""))
            orig_filename = safe_filename(request.form.get("filename", ""))
            temp_path = os.path.join(TEMP_FOLDER, temp_id)

            if os.path.isfile(temp_path) and orig_filename and is_allowed_file(orig_filename):
                subpath = request.form.get('conflict_subpath', '')
                if choice == "replace":
                    dest_path = os.path.join(target_dir, subpath, orig_filename)
                    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                    shutil.move(temp_path, dest_path)
                    rel_path = os.path.join(current_folder, orig_filename).replace("\\", "/")
                    start_file_processing(dest_path, rel_path)
                    flash(f"Файл «{orig_filename}» обновлён.", "success")
                elif choice == "keep_both":
                    new_filename = get_unique_filename(target_dir, orig_filename)
                    dest_path = os.path.join(target_dir, new_filename)
                    shutil.move(temp_path, dest_path)
                    rel_path = os.path.join(current_folder, new_filename).replace("\\", "/")
                    start_file_processing(dest_path, rel_path)
                    flash(f"Файл сохранён как «{new_filename}».", "success")
                else:
                    os.remove(temp_path)
                    flash("Загрузка отменена.", "error")

        elif action == "delete_file":
            filename = os.path.basename(request.form.get("filename", ""))
            file_path = os.path.join(target_dir, filename)
            if filename and is_safe_subpath(os.path.join(current_folder, filename)) and os.path.isfile(file_path):
                os.remove(file_path)
                rel_path = os.path.join(current_folder, filename).replace("\\", "/")
                delete_status(rel_path)
                flash(f"Файл «{filename}» удалён.", "success")

        elif action == "delete_folder":
            folder_name = os.path.basename(request.form.get("folder_name", ""))
            folder_subpath = os.path.join(current_folder, folder_name)
            folder_path = os.path.join(target_dir, folder_name)
            if folder_name and is_safe_subpath(folder_subpath) and os.path.isdir(folder_path):
                shutil.rmtree(folder_path)
                delete_folder_statuses(folder_subpath.replace("\\", "/"))
                flash(f"Папка «{folder_name}» удалена.", "success")

        return redirect(url_for("projects.projects", folder=current_folder))

    # GET-запрос (отрисовка страницы)
    conflict_file = os.path.basename(request.args.get("conflict_file", ""))
    temp_id = os.path.basename(request.args.get("temp_id", ""))
    conflict_data = None
    if conflict_file and temp_id and os.path.isfile(os.path.join(TEMP_FOLDER, temp_id)):
        conflict_data = {"filename": conflict_file, "temp_id": temp_id}

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

    folders = []
    files = []
    statuses = get_statuses()
    is_root = (current_folder == "")

    if is_root:
        for root, dirs, file_names in os.walk(target_dir):
            for item in sorted(dirs, key=str.lower):
                full_path = os.path.join(root, item)
                rel_path = os.path.relpath(full_path, UPLOAD_FOLDER).replace("\\", "/")
                if root == target_dir:
                    folders.append({"name": item, "path": rel_path, "is_empty": len(os.listdir(full_path)) == 0})
            
            for file in sorted(file_names, key=str.lower):
                if is_allowed_file(file):
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, UPLOAD_FOLDER).replace("\\", "/")
                    stats = os.stat(full_path)
                    status_text = statuses.get(rel_path, "Ожидает обработки")
                    status_index = VALID_STATUSES.index(status_text) if status_text in VALID_STATUSES else 0
                    files.append({
                        "name": file, "size": format_size(stats.st_size),
                        "date": datetime.fromtimestamp(stats.st_mtime).strftime("%d.%m.%Y %H:%M"),
                        "status": status_text, "status_index": status_index,
                        "folder": os.path.dirname(rel_path)
                    })
    else:
        for item in os.listdir(target_dir):
            full_path = os.path.join(target_dir, item)
            rel_path = os.path.join(current_folder, item).replace("\\", "/")
            if os.path.isdir(full_path):
                folders.append({"name": item, "path": rel_path, "is_empty": len(os.listdir(full_path)) == 0})
            elif is_allowed_file(item):
                stats = os.stat(full_path)
                status_text = statuses.get(rel_path, "Ожидает обработки")
                status_index = VALID_STATUSES.index(status_text) if status_text in VALID_STATUSES else 0
                files.append({
                    "name": item, "size": format_size(stats.st_size),
                    "date": datetime.fromtimestamp(stats.st_mtime).strftime("%d.%m.%Y %H:%M"),
                    "status": status_text, "status_index": status_index,
                    "folder": current_folder
                })

    parent_folder = os.path.dirname(current_folder).replace("\\", "/") if current_folder else None

    return render_template(
        "index.html", title="Проекты", folders=folders, files=files,
        current_folder=current_folder, parent_folder=parent_folder,
        valid_statuses=VALID_STATUSES, viewed_file=viewed_file, conflict_data=conflict_data
    )