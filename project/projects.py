import os
import json
import uuid
import shutil
import time
import threading
from datetime import datetime
from werkzeug.utils import secure_filename
from flask import Blueprint, render_template, request, redirect, url_for, flash

from auth import (
    login_required, current_user, can_read, can_write, can_delete,
    get_folder_permission, set_folder_owner, delete_folder_acl,
    grant_access, get_users,
)

# Настройки
UPLOAD_FOLDER = 'uploads'
TEMP_FOLDER = '.temp_uploads'
STATUS_FILE = 'statuses.json'
DESCRIPTIONS_FILE = 'project_descriptions.json'

ALLOWED_EXTENSIONS = {'.md', '.markdown', '.txt'}
VALID_STATUSES = [
    "Ожидает обработки",
    "Обрабатывается",
    "Готов к поиску",
    "Ошибка обработки"
]

projects_bp = Blueprint('projects', __name__, template_folder='templates')


# --- Описания проектов ---
def get_descriptions():
    if os.path.exists(DESCRIPTIONS_FILE):
        with open(DESCRIPTIONS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_description(rel_path, description):
    descriptions = get_descriptions()
    if description.strip():
        descriptions[rel_path] = description.strip()
    else:
        descriptions.pop(rel_path, None)

    with open(DESCRIPTIONS_FILE, 'w', encoding='utf-8') as f:
        json.dump(descriptions, f, ensure_ascii=False, indent=2)


def delete_folder_description(folder_rel_path):
    prefix = folder_rel_path.rstrip("/") + "/"
    descriptions = get_descriptions()
    updated = {k: v for k, v in descriptions.items()
               if k != folder_rel_path and not k.startswith(prefix)}

    if len(updated) != len(descriptions):
        with open(DESCRIPTIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(updated, f, ensure_ascii=False, indent=2)


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


# --- Работа со статусами ---
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
        if not os.path.exists(full_path):
            return
        save_status(rel_path, "Обрабатывается")

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
@login_required
def projects():
    username = current_user()
    current_folder = os.path.normpath(request.args.get("folder", "")).strip("/\\")
    if current_folder == ".":
        current_folder = ""
    if not is_safe_subpath(current_folder):
        current_folder = ""

    # --- проверка доступа к текущей папке ---
    if current_folder and not can_read(username, current_folder):
        flash("Нет доступа к этой папке.", "error")
        return redirect(url_for("projects.projects"))

    target_dir = os.path.join(UPLOAD_FOLDER, current_folder)
    os.makedirs(target_dir, exist_ok=True)

    if request.method == "POST":
        action = request.form.get("action")

        if action == "create_folder":
            if not can_write(username, current_folder):
                flash("Недостаточно прав для создания папки.", "error")
                return redirect(url_for("projects.projects", folder=current_folder))

            folder_name = os.path.basename(request.form.get("folder_name", "").strip())
            if folder_name and folder_name not in (".", ".."):
                new_rel = os.path.join(current_folder, folder_name).replace("\\", "/")
                os.makedirs(os.path.join(target_dir, folder_name), exist_ok=True)
                set_folder_owner(new_rel, username)

        elif action == "upload_file":
            if not can_write(username, current_folder):
                flash("Недостаточно прав для загрузки файлов.", "error")
                return redirect(url_for("projects.projects", folder=current_folder))

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
                    new_rel = os.path.join(current_folder, root_folder_name).replace("\\", "/")
                    set_folder_owner(new_rel, username)

            for file in valid_files:
                raw_path = file.filename.replace("\\", "/")
                path_parts = [safe_filename(part) for part in raw_path.split("/") if part]
                if not path_parts:
                    continue

                filename = path_parts[-1]
                if filename.startswith(".") or filename.lower() in ("thumbs.db", "desktop.ini"):
                    continue
                if not is_allowed_file(filename):
                    continue

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
                return redirect(url_for(
                    "projects.projects", folder=current_folder,
                    conflict_file=conflict_file, temp_id=temp_id,
                    conflict_subpath=conflict_subpath
                ))
            elif success_count > 0:
                flash(f"Успешно загружено файлов: {success_count}.", "success")
            else:
                flash("Не найдено подходящих файлов (.md, .markdown, .txt) для загрузки.", "error")

        elif action == "resolve_conflict":
            if not can_write(username, current_folder):
                flash("Недостаточно прав.", "error")
                return redirect(url_for("projects.projects", folder=current_folder))

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
                    rel_path = os.path.join(current_folder, subpath, orig_filename).replace("\\", "/")
                    start_file_processing(dest_path, rel_path)
                    flash(f"Файл «{orig_filename}» обновлён.", "success")
                elif choice == "keep_both":
                    new_filename = get_unique_filename(os.path.dirname(os.path.join(target_dir, subpath, orig_filename)) or target_dir, orig_filename)
                    dest_path = os.path.join(target_dir, subpath, new_filename)
                    shutil.move(temp_path, dest_path)
                    rel_path = os.path.join(current_folder, subpath, new_filename).replace("\\", "/")
                    start_file_processing(dest_path, rel_path)
                    flash(f"Файл сохранён как «{new_filename}».", "success")
                else:
                    os.remove(temp_path)
                    flash("Загрузка отменена.", "error")

        elif action == "edit_description":
            if not can_write(username, current_folder):
                flash("Недостаточно прав.", "error")
                return redirect(url_for("projects.projects", folder=current_folder))

            folder_name = request.form.get("folder_name", "")
            new_description = request.form.get("description", "")
            if folder_name and is_safe_subpath(folder_name):
                save_description(folder_name, new_description)
                flash("Описание проекта обновлено.", "success")

        elif action == "delete_file":
            if not can_write(username, current_folder):
                flash("Недостаточно прав.", "error")
                return redirect(url_for("projects.projects", folder=current_folder))

            filename = os.path.basename(request.form.get("filename", ""))
            file_path = os.path.join(target_dir, filename)
            if filename and is_safe_subpath(os.path.join(current_folder, filename)) and os.path.isfile(file_path):
                os.remove(file_path)
                rel_path = os.path.join(current_folder, filename).replace("\\", "/")
                delete_status(rel_path)
                flash(f"Файл «{filename}» удалён.", "success")

        elif action == "delete_folder":
            folder_name = os.path.basename(request.form.get("folder_name", ""))
            folder_subpath = os.path.join(current_folder, folder_name).replace("\\", "/")
            if not can_delete(username, folder_subpath):
                flash("Удалять папку может только владелец.", "error")
                return redirect(url_for("projects.projects", folder=current_folder))

            folder_path = os.path.join(target_dir, folder_name)
            if folder_name and is_safe_subpath(folder_subpath) and os.path.isdir(folder_path):
                shutil.rmtree(folder_path)
                delete_folder_statuses(folder_subpath)
                delete_folder_description(folder_subpath)
                delete_folder_acl(folder_subpath)
                flash(f"Папка «{folder_name}» удалена.", "success")

        elif action == "rename_folder":
            old_name = os.path.basename(request.form.get("old_name", ""))
            new_name = safe_filename(request.form.get("new_name", "").strip())
            old_rel = os.path.join(current_folder, old_name).replace("\\", "/")

            if not can_delete(username, old_rel):
                flash("Переименовывать папку может только владелец.", "error")
                return redirect(url_for("projects.projects", folder=current_folder))

            if old_name and new_name and new_name not in (".", ".."):
                old_path = os.path.join(target_dir, old_name)
                new_path = os.path.join(target_dir, new_name)

                if os.path.isdir(old_path) and not os.path.exists(new_path):
                    os.rename(old_path, new_path)
                    new_rel = os.path.join(current_folder, new_name).replace("\\", "/")

                    # Переносим владельца в ACL
                    set_folder_owner(new_rel, get_folder_permission(username, old_rel) and username or username)
                    delete_folder_acl(old_rel)

                    flash(f"Папка «{old_name}» переименована в «{new_name}».", "success")
                else:
                    flash("Ошибка: папка с таким именем уже существует или исходная папка не найдена.", "error")

        elif action == "set_acl":
            folder_path = request.form.get("folder_path", "").strip("/")
            target_user = request.form.get("username", "").strip()
            level = request.form.get("level", "viewer")

            if not can_delete(username, folder_path):
                flash("Управлять доступом может только владелец.", "error")
                return redirect(url_for("projects.projects", folder=current_folder))

            if target_user in get_users():
                grant_access(folder_path, target_user, level)
                flash(f"Доступ выдан: {target_user} → {level}.", "success")
            else:
                flash("Пользователь не найден.", "error")

        return redirect(url_for("projects.projects", folder=current_folder))

    # ===== GET =====
    conflict_file = os.path.basename(request.args.get("conflict_file", ""))
    temp_id = os.path.basename(request.args.get("temp_id", ""))
    conflict_data = None
    if conflict_file and temp_id and os.path.isfile(os.path.join(TEMP_FOLDER, temp_id)):
        conflict_data = {"filename": conflict_file, "temp_id": temp_id}

    # Просмотр файла
    view_filename = request.args.get("view", "").replace("\\", "/").strip("/")
    viewed_file = None
    if view_filename:
        if "/" in view_filename:
            view_path = os.path.join(UPLOAD_FOLDER, view_filename)
            parent_of_view = os.path.dirname(view_filename)
        else:
            view_path = os.path.join(target_dir, view_filename)
            parent_of_view = current_folder

        if can_read(username, parent_of_view) and os.path.isfile(view_path):
            try:
                with open(view_path, "r", encoding="utf-8") as f:
                    file_content = f.read()
            except UnicodeDecodeError:
                with open(view_path, "r", encoding="cp1251", errors="replace") as f:
                    file_content = f.read()
            viewed_file = {"name": os.path.basename(view_filename), "content": file_content}

    folders = []
    files = []
    statuses = get_statuses()
    is_root = (current_folder == "")

    if is_root:
        for root, dirs, file_names in os.walk(target_dir):
            for item in sorted(dirs, key=str.lower):
                full_path = os.path.join(root, item)
                rel_path = os.path.relpath(full_path, UPLOAD_FOLDER).replace("\\", "/")
                if not can_read(username, rel_path):
                    continue
                if root == target_dir:
                    folders.append({"name": item, "path": rel_path, "is_empty": len(os.listdir(full_path)) == 0})

            for file in sorted(file_names, key=str.lower):
                if is_allowed_file(file):
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, UPLOAD_FOLDER).replace("\\", "/")
                    parent_rel = os.path.dirname(rel_path)
                    if not can_read(username, parent_rel):
                        continue
                    stats = os.stat(full_path)
                    status_text = statuses.get(rel_path, "Ожидает обработки")
                    status_index = VALID_STATUSES.index(status_text) if status_text in VALID_STATUSES else 0
                    files.append({
                        "name": file, "size": format_size(stats.st_size),
                        "date": datetime.fromtimestamp(stats.st_mtime).strftime("%d.%m.%Y %H:%M"),
                        "status": status_text, "status_index": status_index,
                        "folder": parent_rel
                    })
    else:
        for item in os.listdir(target_dir):
            full_path = os.path.join(target_dir, item)
            rel_path = os.path.join(current_folder, item).replace("\\", "/")
            if os.path.isdir(full_path):
                if not can_read(username, rel_path):
                    continue
                folders.append({"name": item, "path": rel_path, "is_empty": len(os.listdir(full_path)) == 0})
            elif is_allowed_file(item):
                if not can_read(username, current_folder):
                    continue
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
    descriptions = get_descriptions()

    return render_template(
        "index.html", title="Проекты", folders=folders, files=files,
        current_folder=current_folder, parent_folder=parent_folder,
        valid_statuses=VALID_STATUSES, viewed_file=viewed_file, conflict_data=conflict_data,
        descriptions=descriptions,
        get_folder_permission=get_folder_permission,
        all_users=list(get_users().keys()),
    )