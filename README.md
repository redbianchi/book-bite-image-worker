# Book Bite Render Worker

Small FastAPI service for generating Book Bite images from Dropbox assets.

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

## Render setup

1. Put this folder in a GitHub repository.
2. In Render, create a new Web Service from the repo.
3. Use:
   - Build command: `pip install -r requirements.txt`
   - Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. Add environment variables:
   - `WEBHOOK_SECRET`: a long random string Zapier must send in the `X-Book-Bite-Secret` header.
   - `DROPBOX_REFRESH_TOKEN`
   - `DROPBOX_APP_KEY`
   - `DROPBOX_APP_SECRET`

`DROPBOX_ACCESS_TOKEN` also works for early testing, but a refresh token is better for production.

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
