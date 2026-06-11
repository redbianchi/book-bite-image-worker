from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps


ROOT = Path(__file__).resolve().parents[1]
ASSETS_DIR = ROOT / "assets"
APP_TEMPLATE = ASSETS_DIR / "BLANK_book-bite_1080x608.jpg"
BLOG_INFO_BY_MINUTES = {
    "12": ASSETS_DIR / "blog-info-12min.png",
    "13": ASSETS_DIR / "blog-info-13min.png",
    "14": ASSETS_DIR / "blog-info-14min.png",
    "15": ASSETS_DIR / "blog-info-15min.png",
}


@dataclass(frozen=True)
class PortraitCropHints:
    face_x: float
    face_y: float
    app_crop_width: int
    blog_crop_size: int


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_") or "book_bite"


def open_rgb(path: Path) -> Image.Image:
    return ImageOps.exif_transpose(Image.open(path)).convert("RGB")


def open_rgba(path: Path) -> Image.Image:
    return ImageOps.exif_transpose(Image.open(path)).convert("RGBA")


def nonwhite_bbox(image: Image.Image, threshold: int = 248) -> tuple[int, int, int, int]:
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    xs: list[int] = []
    ys: list[int] = []
    for y in range(rgba.height):
        for x in range(rgba.width):
            r, g, b, a = pixels[x, y]
            if a and (r < threshold or g < threshold or b < threshold):
                xs.append(x)
                ys.append(y)
    if not xs:
        return (0, 0, rgba.width, rgba.height)
    return (min(xs), min(ys), max(xs) + 1, max(ys) + 1)


def crop_with_mirror_padding(image: Image.Image, left: int, top: int, width: int, height: int) -> Image.Image:
    pad_left = max(0, -left)
    pad_top = max(0, -top)
    pad_right = max(0, left + width - image.width)
    pad_bottom = max(0, top + height - image.height)

    if any((pad_left, pad_top, pad_right, pad_bottom)):
        padded = ImageOps.expand(
            image,
            border=(pad_left, pad_top, pad_right, pad_bottom),
            fill=image.getpixel((0, 0)),
        )
        if pad_left:
            src_w = min(pad_left, image.width)
            left_src = image.crop((0, 0, src_w, image.height)).transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            padded.paste(left_src.resize((pad_left, image.height)), (0, pad_top))
        if pad_right:
            src_w = min(pad_right, image.width)
            right_src = image.crop((image.width - src_w, 0, image.width, image.height)).transpose(
                Image.Transpose.FLIP_LEFT_RIGHT
            )
            padded.paste(right_src.resize((pad_right, image.height)), (pad_left + image.width, pad_top))
        if pad_top:
            top_src = padded.crop((0, pad_top, padded.width, pad_top * 2)).transpose(Image.Transpose.FLIP_TOP_BOTTOM)
            padded.paste(top_src, (0, 0))
        if pad_bottom:
            bottom_src = padded.crop(
                (0, pad_top + image.height - pad_bottom, padded.width, pad_top + image.height)
            ).transpose(Image.Transpose.FLIP_TOP_BOTTOM)
            padded.paste(bottom_src, (0, pad_top + image.height))
        image = padded
        left += pad_left
        top += pad_top

    return image.crop((left, top, left + width, top + height))


def _box_area(box: tuple[float, float, float, float]) -> float:
    return box[2] * box[3]


def _box_iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    left = max(ax, bx)
    top = max(ay, by)
    right = min(ax + aw, bx + bw)
    bottom = min(ay + ah, by + bh)
    if right <= left or bottom <= top:
        return 0
    intersection = (right - left) * (bottom - top)
    return intersection / (_box_area(a) + _box_area(b) - intersection)


def _dedupe_boxes(boxes: list[tuple[float, float, float, float]]) -> list[tuple[float, float, float, float]]:
    kept: list[tuple[float, float, float, float]] = []
    for box in sorted(boxes, key=_box_area, reverse=True):
        if all(_box_iou(box, existing) < 0.35 for existing in kept):
            kept.append(box)
    return kept


def _detect_faces(portrait: Image.Image) -> list[tuple[float, float, float, float]]:
    try:
        import cv2
        import numpy as np
    except Exception:
        return []

    width, height = portrait.size
    rgb = np.array(portrait.convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

    scale = min(1.0, 1000 / max(width, height))
    if scale < 1:
        gray_small = cv2.resize(gray, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)
    else:
        gray_small = gray
    gray_small = cv2.equalizeHist(gray_small)

    def detect_with_cascade(cascade_name: str, image, flipped: bool = False) -> list[tuple[float, float, float, float]]:
        cascade_path = Path(cv2.data.haarcascades) / cascade_name
        cascade = cv2.CascadeClassifier(str(cascade_path))
        if cascade.empty():
            return []
        min_size = max(28, round(min(image.shape[:2]) * 0.08))
        found = cascade.detectMultiScale(
            image,
            scaleFactor=1.05,
            minNeighbors=4,
            minSize=(min_size, min_size),
        )
        boxes: list[tuple[float, float, float, float]] = []
        image_w = image.shape[1]
        for x, y, w, h in found:
            if flipped:
                x = image_w - x - w
            boxes.append((x / scale, y / scale, w / scale, h / scale))
        return boxes

    boxes: list[tuple[float, float, float, float]] = []
    boxes.extend(detect_with_cascade("haarcascade_frontalface_default.xml", gray_small))
    boxes.extend(detect_with_cascade("haarcascade_frontalface_alt2.xml", gray_small))
    boxes.extend(detect_with_cascade("haarcascade_profileface.xml", gray_small))
    boxes.extend(
        detect_with_cascade(
            "haarcascade_profileface.xml",
            cv2.flip(gray_small, 1),
            flipped=True,
        )
    )

    min_area = width * height * 0.01
    filtered = [
        box
        for box in boxes
        if _box_area(box) >= min_area and box[2] > 0 and box[3] > 0
    ]
    return _dedupe_boxes(filtered)


def portrait_crop_hints(
    portrait: Image.Image,
    face_x: float | None = None,
    face_y: float | None = None,
) -> PortraitCropHints:
    width, height = portrait.size
    default_face_x = width / 2
    default_face_y = height * 0.35
    default_app_crop_width = round(width * 0.825)
    default_blog_crop_size = round(min(portrait.size) * 0.52)

    if face_x is not None or face_y is not None:
        return PortraitCropHints(
            face_x=face_x if face_x is not None else default_face_x,
            face_y=face_y if face_y is not None else default_face_y,
            app_crop_width=default_app_crop_width,
            blog_crop_size=default_blog_crop_size,
        )

    faces = _detect_faces(portrait)
    if not faces:
        return PortraitCropHints(default_face_x, default_face_y, default_app_crop_width, default_blog_crop_size)

    max_area = _box_area(faces[0])
    selected = [box for box in faces if _box_area(box) >= max_area * 0.35]
    left = min(box[0] for box in selected)
    top = min(box[1] for box in selected)
    right = max(box[0] + box[2] for box in selected)
    bottom = max(box[1] + box[3] for box in selected)
    face_w = right - left
    face_h = bottom - top
    tightness = max(face_w / width, face_h / height)

    face_center_x = left + face_w / 2
    face_center_y = top + face_h * (0.62 if tightness > 0.62 else 0.56)

    max_dim = max(width, height)
    max_crop = round(max_dim * 0.95)
    if len(selected) > 1:
        blog_crop = max(default_blog_crop_size, face_w * 1.35, face_h * 1.45)
        app_crop = max(default_app_crop_width, face_w * 1.35, face_h * 1.35)
    else:
        blog_crop = max(default_blog_crop_size, face_w * 1.65, face_h * 1.75)
        app_crop = max(default_app_crop_width, face_w * 1.45, face_h * 1.55)

    if tightness > 0.62:
        blog_crop = max(blog_crop, face_h * 1.9)
        app_crop = max(app_crop, face_h * 1.65)

    return PortraitCropHints(
        face_x=face_center_x,
        face_y=face_center_y,
        app_crop_width=round(min(max_crop, app_crop)),
        blog_crop_size=round(min(max_crop, blog_crop)),
    )


def make_author_badge(portrait: Image.Image, size: int, face_x: float, face_y: float, crop_size: int) -> Image.Image:
    scale = 8
    big_size = size * scale
    crop = crop_with_mirror_padding(
        portrait,
        round(face_x - crop_size / 2),
        round(face_y - crop_size / 2),
        crop_size,
        crop_size,
    )
    crop = crop.resize((big_size, big_size), Image.Resampling.LANCZOS).convert("RGBA")

    mask = Image.new("L", (big_size, big_size), 0)
    draw = ImageDraw.Draw(mask)
    inset = 3 * scale
    draw.ellipse((inset, inset, big_size - inset - 1, big_size - inset - 1), fill=255)

    out = Image.new("RGBA", (big_size, big_size), (255, 255, 255, 0))
    ring = Image.new("RGBA", (big_size, big_size), (255, 255, 255, 0))
    rd = ImageDraw.Draw(ring)
    rd.ellipse((0, 0, big_size - 1, big_size - 1), outline=(218, 222, 228, 255), width=scale)
    out.alpha_composite(ring)
    out.paste(crop, (0, 0), mask)
    return out.resize((size, size), Image.Resampling.LANCZOS)


def generate_app(
    cover: Image.Image,
    portrait: Image.Image,
    out_dir: Path,
    name: str,
    face_x: float,
    face_y: float,
    crop_w: int,
) -> dict[str, Path]:
    width, height = 1080, 608
    canvas = open_rgb(APP_TEMPLATE).resize((width, height), Image.Resampling.LANCZOS)

    app_panel_x = 348
    cover_x, cover_y, cover_h = 132, 76, 460
    cover_w = round(cover_h * cover.width / cover.height)
    book_right = cover_x + cover_w
    author_center_x = round((book_right + width) / 2)

    panel_w = width - app_panel_x
    max_crop_w_without_padding = round(portrait.height * panel_w / height)
    if portrait.width / portrait.height > panel_w / height:
        crop_w = min(crop_w, max_crop_w_without_padding)
    crop_h = round(crop_w * height / panel_w)
    face_panel_x = author_center_x - app_panel_x
    crop_left = round(face_x - face_panel_x * crop_w / panel_w)
    crop_top = round(face_y - 250 * crop_h / height)
    if crop_w <= portrait.width:
        crop_left = min(max(0, crop_left), portrait.width - crop_w)
    if crop_h <= portrait.height:
        crop_top = min(max(0, crop_top), portrait.height - crop_h)
    portrait_panel = crop_with_mirror_padding(portrait, crop_left, crop_top, crop_w, crop_h)
    portrait_panel = portrait_panel.resize((panel_w, height), Image.Resampling.LANCZOS)
    canvas.paste(portrait_panel, (app_panel_x, 0))

    cover_scaled = cover.resize((cover_w, cover_h), Image.Resampling.LANCZOS)
    canvas.paste(cover_scaled, (cover_x, cover_y))

    jpg_path = out_dir / f"{name}_app_1080x608.jpg"
    webp_path = out_dir / f"{name}_app_1080x608.webp"
    canvas.save(jpg_path, quality=100, subsampling=0)
    canvas.save(webp_path, quality=95, method=6)
    return {"app_jpg": jpg_path, "app_webp": webp_path}


def generate_blog(
    cover: Image.Image,
    portrait: Image.Image,
    out_dir: Path,
    name: str,
    duration: str,
    face_x: float,
    face_y: float,
    blog_crop_size: int,
) -> dict[str, Path]:
    width, height = 717, 448
    canvas = Image.new("RGBA", (width, height), "white")

    cover_x, cover_y, cover_h = 28, 24, 388
    cover_w = round(cover_h * cover.width / cover.height)
    shadow = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    sd = ImageDraw.Draw(shadow, "RGBA")
    sd.rectangle((cover_x + 10, cover_y + 11, cover_x + cover_w + 10, cover_y + cover_h + 11), fill=(0, 0, 0, 42))
    shadow = shadow.filter(ImageFilter.GaussianBlur(12))
    canvas.alpha_composite(shadow)

    cover_scaled = cover.resize((cover_w, cover_h), Image.Resampling.LANCZOS).convert("RGBA")
    canvas.alpha_composite(cover_scaled, (cover_x, cover_y))

    badge = make_author_badge(portrait, 116, face_x, face_y, blog_crop_size)
    canvas.alpha_composite(badge, (248, 306))

    info = open_rgba(BLOG_INFO_BY_MINUTES[duration])
    info = info.crop(nonwhite_bbox(info))
    info_h = round(260 * info.height / info.width)
    info = info.resize((260, info_h), Image.Resampling.LANCZOS)
    canvas.alpha_composite(info, (372, 136))

    jpg_path = out_dir / f"{name}_blog_inline_717x448.jpg"
    canvas.convert("RGB").save(jpg_path, quality=100, subsampling=0)
    return {"blog_jpg": jpg_path}


def generate_images(
    cover_path: Path,
    author_path: Path,
    out_dir: Path,
    name: str,
    duration: str = "14",
    layout: str = "both",
    face_x: float | None = None,
    face_y: float | None = None,
) -> dict[str, Path]:
    cover = open_rgb(cover_path)
    portrait = open_rgb(author_path)
    crop_hints = portrait_crop_hints(portrait, face_x=face_x, face_y=face_y)
    name = slugify(name)

    out_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, Path] = {}
    if layout in ("both", "app"):
        outputs.update(
            generate_app(
                cover,
                portrait,
                out_dir,
                name,
                crop_hints.face_x,
                crop_hints.face_y,
                crop_hints.app_crop_width,
            )
        )
    if layout in ("both", "blog"):
        outputs.update(
            generate_blog(
                cover,
                portrait,
                out_dir,
                name,
                duration,
                crop_hints.face_x,
                crop_hints.face_y,
                crop_hints.blog_crop_size,
            )
        )
    return outputs
