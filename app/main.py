from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from app.dropbox_io import (
    DropboxConfigError,
    clean_dropbox_path,
    client,
    download_file,
    ensure_folder,
    join_dropbox,
    resolve_named_image,
    upload_file,
)
from app.image_generator import generate_images, slugify


app = FastAPI(title="Book Bite Image Worker")


class GenerateRequest(BaseModel):
    folder_path: str = Field(..., description="Dropbox Book Bite folder path.")
    slug: str | None = Field(None, description="Output filename slug. Defaults to folder name.")
    duration: Literal["12", "13", "14", "15"] = "14"
    layout: Literal["both", "app", "blog"] = "both"
    raw_subfolder: str = "raw images"
    output_subfolder: str = "generated images"
    cover_filename: str = "cover.jpg"
    author_filename: str = "author.jpg"
    face_x: float | None = None
    face_y: float | None = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def require_secret(header_secret: str | None) -> None:
    expected = os.getenv("WEBHOOK_SECRET")
    if expected and header_secret != expected:
        raise HTTPException(status_code=401, detail="Invalid webhook secret.")


@app.post("/generate-book-bite")
def generate_book_bite(
    payload: GenerateRequest,
    x_book_bite_secret: str | None = Header(default=None),
) -> dict[str, object]:
    require_secret(x_book_bite_secret)

    folder = clean_dropbox_path(payload.folder_path)
    raw_folder = join_dropbox(folder, payload.raw_subfolder)
    output_folder = join_dropbox(folder, payload.output_subfolder)
    name = slugify(payload.slug or Path(folder).name)

    try:
        dbx = client()
    except DropboxConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    try:
        cover_dropbox_path = resolve_named_image(dbx, raw_folder, payload.cover_filename, ("cover", "jacket", "book"))
        author_dropbox_path = resolve_named_image(dbx, raw_folder, payload.author_filename, ("author", "headshot", "photo", "web"))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

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
                duration=payload.duration,
                layout=payload.layout,
                face_x=payload.face_x,
                face_y=payload.face_y,
            )
            ensure_folder(dbx, output_folder)
            uploaded = {}
            for key, local_path in outputs.items():
                remote_path = join_dropbox(output_folder, local_path.name)
                shared_link = upload_file(dbx, local_path, remote_path)
                uploaded[key] = {"path": remote_path, "url": shared_link}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "status": "generated",
        "folder_path": folder,
        "raw_folder": raw_folder,
        "output_folder": output_folder,
        "duration": payload.duration,
        "layout": payload.layout,
        "cover": cover_dropbox_path,
        "author": author_dropbox_path,
        "outputs": uploaded,
    }
