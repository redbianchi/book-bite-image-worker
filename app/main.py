from __future__ import annotations

import os
import tempfile
from pathlib import Path

from flask import Flask, jsonify, request

from app.dropbox_io import (
    DropboxConfigError,
    account_summary,
    clean_dropbox_path,
    client,
    download_file,
    ensure_folder,
    join_dropbox,
    resolve_named_image,
    upload_file,
)
from app.image_generator import generate_images, slugify


app = Flask(__name__)


def error_response(message: str, status_code: int):
    response = jsonify({"status": "error", "detail": message})
    response.status_code = status_code
    return response


def require_secret():
    expected = os.getenv("WEBHOOK_SECRET")
    if expected and request.headers.get("X-Book-Bite-Secret") != expected:
        return error_response("Invalid webhook secret.", 401)
    return None


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/")
def root():
    return jsonify(
        {
            "status": "ok",
            "service": "Book Bite Image Worker",
            "health": "/health",
            "generate": "/generate-book-bite",
            "debug_account": "/debug/account",
            "debug_list_folder": "/debug/list-folder",
        }
    )


@app.post("/generate-book-bite")
def generate_book_bite():
    secret_error = require_secret()
    if secret_error:
        return secret_error

    payload = request.get_json(silent=True) or {}
    folder_path = payload.get("folder_path")
    if not folder_path:
        return error_response("Missing required field: folder_path", 400)

    duration = str(payload.get("duration", "14"))
    if duration not in {"12", "13", "14", "15"}:
        return error_response("duration must be one of: 12, 13, 14, 15", 400)

    layout = payload.get("layout", "both")
    if layout not in {"both", "app", "blog"}:
        return error_response("layout must be one of: both, app, blog", 400)

    folder = clean_dropbox_path(folder_path)
    raw_subfolder = payload.get("raw_subfolder", "raw images")
    output_subfolder = payload.get("output_subfolder", "generated images")
    cover_filename = payload.get("cover_filename", "cover.jpg")
    author_filename = payload.get("author_filename", "author.jpg")
    raw_folder = join_dropbox(folder, raw_subfolder)
    output_folder = join_dropbox(folder, output_subfolder)
    name = slugify(payload.get("slug") or Path(folder).name)
    face_x = payload.get("face_x")
    face_y = payload.get("face_y")

    try:
        dbx = client()
    except DropboxConfigError as exc:
        return error_response(str(exc), 500)

    try:
        cover_dropbox_path = resolve_named_image(dbx, raw_folder, cover_filename, ("cover", "jacket", "book"))
        author_dropbox_path = resolve_named_image(dbx, raw_folder, author_filename, ("author", "headshot", "photo", "web"))
    except Exception as exc:
        return error_response(str(exc), 422)

    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        cover_local = temp / "cover"
        author_local = temp / "author"
        out_dir = temp / "outputs"

        try:
            download_file(dbx, cover_dropbox_path, cover_local)
            download_file(dbx, author_dropbox_path, author_local)
            outputs = generate_images(
                cover_path=cover_local,
                author_path=author_local,
                out_dir=out_dir,
                name=name,
                duration=duration,
                layout=layout,
                face_x=float(face_x) if face_x is not None else None,
                face_y=float(face_y) if face_y is not None else None,
            )
            ensure_folder(dbx, output_folder)
            uploaded = {}
            for key, local_path in outputs.items():
                remote_path = join_dropbox(output_folder, local_path.name)
                shared_link = upload_file(dbx, local_path, remote_path)
                uploaded[key] = {"path": remote_path, "url": shared_link}
        except Exception as exc:
            return error_response(str(exc), 500)

    return jsonify(
        {
            "status": "generated",
            "folder_path": folder,
            "raw_folder": raw_folder,
            "output_folder": output_folder,
            "duration": duration,
            "layout": layout,
            "cover": cover_dropbox_path,
            "author": author_dropbox_path,
            "outputs": uploaded,
        }
    )


@app.post("/debug/list-folder")
def debug_list_folder():
    secret_error = require_secret()
    if secret_error:
        return secret_error

    payload = request.get_json(silent=True) or {}
    folder = clean_dropbox_path(payload.get("folder_path", ""))

    try:
        dbx = client()
        entries = dbx.files_list_folder(folder).entries
    except DropboxConfigError as exc:
        return error_response(str(exc), 500)
    except Exception as exc:
        return error_response(str(exc), 422)

    return jsonify(
        {
            "status": "ok",
            "folder_path": folder or "/",
            "entries": [
                {
                    "name": getattr(entry, "name", ""),
                    "path": getattr(entry, "path_display", None) or getattr(entry, "path_lower", None),
                    "type": entry.__class__.__name__,
                }
                for entry in entries
            ],
        }
    )


@app.post("/debug/account")
def debug_account():
    secret_error = require_secret()
    if secret_error:
        return secret_error

    try:
        summary = account_summary()
    except DropboxConfigError as exc:
        return error_response(str(exc), 500)
    except Exception as exc:
        return error_response(str(exc), 422)

    return jsonify({"status": "ok", "dropbox": summary})
