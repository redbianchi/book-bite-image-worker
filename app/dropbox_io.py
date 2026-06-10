from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

import dropbox
from dropbox.common import PathRoot
from dropbox.exceptions import ApiError
from dropbox.files import WriteMode


IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


class DropboxConfigError(RuntimeError):
    pass


def base_client() -> dropbox.Dropbox:
    refresh_token = os.getenv("DROPBOX_REFRESH_TOKEN")
    app_key = os.getenv("DROPBOX_APP_KEY")
    app_secret = os.getenv("DROPBOX_APP_SECRET")
    access_token = os.getenv("DROPBOX_ACCESS_TOKEN")

    if refresh_token and app_key and app_secret:
        return dropbox.Dropbox(oauth2_refresh_token=refresh_token, app_key=app_key, app_secret=app_secret)
    if access_token:
        return dropbox.Dropbox(access_token)
    raise DropboxConfigError("Set DROPBOX_REFRESH_TOKEN + DROPBOX_APP_KEY + DROPBOX_APP_SECRET, or DROPBOX_ACCESS_TOKEN.")


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _root_namespace_id(dbx: dropbox.Dropbox) -> str:
    try:
        account = dbx.users_get_current_account()
    except Exception as exc:
        raise DropboxConfigError(
            "Dropbox root namespace mode requires the account_info.read scope. "
            "Add that scope in the Dropbox app console, then generate a new token."
        ) from exc

    root_info = getattr(account, "root_info", None)
    root_namespace_id = getattr(root_info, "root_namespace_id", None)
    if not root_namespace_id:
        raise DropboxConfigError("Could not read a root namespace ID from the Dropbox account.")
    return root_namespace_id


def with_configured_path_root(dbx: dropbox.Dropbox) -> dropbox.Dropbox:
    root_namespace_id = os.getenv("DROPBOX_ROOT_NAMESPACE_ID", "").strip()
    path_root = os.getenv("DROPBOX_PATH_ROOT", "").strip().lower()

    if root_namespace_id:
        return dbx.with_path_root(PathRoot.root(root_namespace_id))
    if path_root in {"root", "team", "team_root"} or _env_flag("DROPBOX_USE_ROOT_NAMESPACE"):
        return dbx.with_path_root(PathRoot.root(_root_namespace_id(dbx)))
    if path_root == "home":
        return dbx.with_path_root(PathRoot.home)
    return dbx


def client() -> dropbox.Dropbox:
    return with_configured_path_root(base_client())


def account_summary() -> dict:
    dbx = base_client()
    account = dbx.users_get_current_account()
    root_info = getattr(account, "root_info", None)
    return {
        "account_id": getattr(account, "account_id", None),
        "email": getattr(account, "email", None),
        "name": getattr(getattr(account, "name", None), "display_name", None),
        "root_namespace_id": getattr(root_info, "root_namespace_id", None),
        "home_namespace_id": getattr(root_info, "home_namespace_id", None),
        "home_path": getattr(root_info, "home_path", None),
        "configured_path_root": os.getenv("DROPBOX_PATH_ROOT", ""),
        "use_root_namespace": _env_flag("DROPBOX_USE_ROOT_NAMESPACE"),
        "has_explicit_root_namespace_id": bool(os.getenv("DROPBOX_ROOT_NAMESPACE_ID", "").strip()),
    }


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

    try:
        entries = dbx.files_list_folder(folder_path).entries
    except ApiError as exc:
        if exc.error.is_path() and exc.error.get_path().is_not_found():
            raise FileNotFoundError(f"Dropbox folder not found: {folder_path}") from exc
        raise
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
