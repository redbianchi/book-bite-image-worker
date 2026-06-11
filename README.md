# Book Bite Render Worker

Small Flask service for generating Book Bite images from Dropbox assets.

## Dropbox folder convention

Each Book Bite folder should contain:

```text
[Book Bite Folder]/
  raw images/
    cover.jpg
    author.jpg
  generated images/
```

The service will write:

```text
generated images/
  [slug]_app_1080x608.jpg
  [slug]_app_1080x608.webp
  [slug]_blog_inline_717x448.jpg
```

The image generator automatically tries to detect faces in `author.jpg`. When it finds a face or face group, it centers the author crop and zooms out for tight archival portraits. If detection fails, it falls back to the standard crop.

## Render setup

1. Put this folder in a GitHub repository.
2. In Render, create a new Web Service from the repo.
3. Use:
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn app.main:app --bind 0.0.0.0:$PORT`
4. Add environment variables:
   - `PYTHON_VERSION`: `3.12.8`
   - `WEBHOOK_SECRET`: a long random string Zapier must send in the `X-Book-Bite-Secret` header.
   - For quick testing: `DROPBOX_ACCESS_TOKEN`
   - For production: `DROPBOX_REFRESH_TOKEN`, `DROPBOX_APP_KEY`, and `DROPBOX_APP_SECRET`
   - If the Dropbox API can see your personal folders but not the shared/team folder, add `DROPBOX_USE_ROOT_NAMESPACE` with value `true`.

The "Generated access token" button in the Dropbox app console creates an access token, not a refresh token. Use it for a smoke test by setting `DROPBOX_ACCESS_TOKEN` in Render. For production, use a refresh token so the service keeps working after short-lived access tokens expire.

## Dropbox team folder access

Some Dropbox Business accounts have a separate team root. On a Mac, this can look like two areas in Finder, such as:

```text
Christopher Chaput/
Heleo Team Folder/
```

By default, the Dropbox API may only look inside the member/personal area. If `debug/list-folder` can list folders such as `/Author Uploads` but cannot find `/Heleo Team Folder`, turn on team-root mode:

1. In the Dropbox app console, make sure the app has `account_info.read` plus the file read/write scopes you already selected.
2. Generate a new token after changing scopes.
3. In Render, update the Dropbox token.
4. In Render, add:

```text
DROPBOX_USE_ROOT_NAMESPACE=true
```

Then redeploy and test:

```text
POST /debug/account
POST /debug/list-folder
```

Use `/debug/account` to confirm Dropbox is returning a `root_namespace_id`. Use `/debug/list-folder` with `{"folder_path": "/"}` to check whether the team folder is now visible.

## Zapier request

Send a POST request to:

```text
https://YOUR-RENDER-SERVICE.onrender.com/generate-book-bite
```

Headers:

```text
Content-Type: application/json
X-Book-Bite-Secret: [WEBHOOK_SECRET]
```

Body:

```json
{
  "folder_path": "/Book Bites and IODs/Amy Kurtz - But You Look Fine",
  "slug": "amy_kurtz_but_you_look_fine",
  "duration": "12",
  "layout": "both"
}
```

If Notion has a Dropbox shared folder link instead of a Dropbox path, send `folder_url` instead:

```json
{
  "folder_url": "https://www.dropbox.com/sh/...",
  "slug": "amy_kurtz_but_you_look_fine",
  "duration": "12"
}
```

`layout` is optional and defaults to `both`. Use `"layout": "app"` or `"layout": "blog"` only when you want one output type.

Optional crop tuning:

```json
{
  "face_x": 770,
  "face_y": 635
}
```

## Notion/Zapier workflow

Recommended trigger:

1. Notion checkbox `Ready for Image Generation` is checked.
2. Zapier sends the row's Dropbox folder path, slug, and duration to this service.
3. This service uploads generated files to Dropbox and returns output links.
4. Zapier writes those links back to Notion and changes status to `Needs Review` or `Complete`.
