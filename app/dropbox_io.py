from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

import dropbox
from dropbox.exceptions import ApiError
from dropbox.files import WriteMode


IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


class DropboxConfigError(RuntimeError):
    pass


def client() -> dropbox.Dropbox:
    refresh_token = os.getenv("DROPBOX_REFRESH_TOKEN")
    app_key = os.getenv("DROPBOX_APP_KEY")
    app_secret = os.getenv("DROPBOX_APP_SECRET")
    access_token = os.getenv("DROPBOX_ACCESS_TOKEN")

    if refresh_token and app_key and app_secret:
        return dropbox.Dropbox(oauth2_refresh_token=refresh_token, app_key=app_key, app_secret=app_secret)
    if access_token:
        return dropbox.Dropbox(access_token)
    raise DropboxConfigError("Set DROPBOX_REFRESH_TOKEN + DROPBOX_APP_KEY + DROPBOX_APP_SECRET, or DROPBOX_ACCESS_TOKEN.")


def clean_dropbox_path(path: str) -> str:
    path = path.strip()
    if not path.startswith("/"):
        path = "/" + path
    return str(PurePosixPath(path))


def join_dropbox(*parts: str) -> str:
    joined = PurePosixPath(parts[0])
    for part in parts[1:]:
        joined = joined / part
    return clean_dropbox_path(str(joined))


def ensure_folder(dbx: dropbox.Dropbox, folder_path: str) -> None:
    try:
        dbx.files_create_folder_v2(folder_path)
    except ApiError as exc:
        if exc.error.is_path() and exc.error.get_path().is_conflict():
            return
        raise


def download_file(dbx: dropbox.Dropbox, dropbox_path: str, local_path: Path) -> None:
    metadata, response = dbx.files_download(dropbox_path)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_bytes(response.content)


def upload_file(dbx: dropbox.Dropbox, local_path: Path, dropbox_path: str) -> str | None:
    dbx.files_upload(local_path.read_bytes(), dropbox_path, mode=WriteMode.overwrite)
    return get_or_create_shared_link(dbx, dropbox_path)


def get_or_create_shared_link(dbx: dropbox.Dropbox, dropbox_path: str) -> str | None:
    try:
        return dbx.sharing_create_shared_link_with_settings(dropbox_path).url
    except ApiError as exc:
        if exc.error.is_shared_link_already_exists():
            links = dbx.sharing_list_shared_links(path=dropbox_path, direct_only=True).links
            if links:
                return links[0].url
        return None


def resolve_named_image(dbx: dropbox.Dropbox, folder_path: str, preferred_name: str, keywords: tuple[str, ...]) -> str:
    exact_path = join_dropbox(folder_path, preferred_name)
    try:
        dbx.files_get_metadata(exact_path)
        return exact_path
    except ApiError:
        pass

    entries = dbx.files_list_folder(folder_path).entries
    image_entries = [
        entry
        for entry in entries
        if getattr(entry, "name", "").lower().endswith(IMAGE_EXTENSIONS)
    ]
    for entry in image_entries:
        lower_name = entry.name.lower()
        if any(keyword in lower_name for keyword in keywords):
            return entry.path_lower or join_dropbox(folder_path, entry.name)

    if len(image_entries) == 1:
        entry = image_entries[0]
        return entry.path_lower or join_dropbox(folder_path, entry.name)

    names = ", ".join(getattr(entry, "name", "") for entry in image_entries) or "no images found"
    raise FileNotFoundError(f"Could not resolve {preferred_name} in {folder_path}. Images found: {names}")
