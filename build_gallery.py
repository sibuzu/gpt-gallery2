#!/usr/bin/env python3
"""Build Gallery 2's image snapshot, counts, and asset versions only."""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

from PIL import Image


SITE_DIR = Path(__file__).resolve().parent
CATEGORIES = ("清新", "性感", "動漫", "故事", "故事2", "漫服")
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def scan_images() -> tuple[list[dict[str, object]], dict[str, object]]:
    images: list[dict[str, object]] = []
    skipped: list[dict[str, str]] = []
    seen: dict[str, str] = {}
    counts = {category: 0 for category in CATEGORIES}

    for category in CATEGORIES:
        directory = SITE_DIR / "images" / category
        if not directory.is_dir():
            raise RuntimeError(f"Missing image directory: {directory}")
        for path in sorted(directory.iterdir()):
            if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            relative_path = path.relative_to(SITE_DIR).as_posix()
            with path.open("rb") as image_file:
                digest = hashlib.file_digest(image_file, "sha256").hexdigest()
            if digest in seen:
                skipped.append({
                    "path": relative_path,
                    "duplicate_of": seen[digest],
                    "reason": "duplicate_hash",
                })
                continue
            seen[digest] = relative_path
            with Image.open(path) as image:
                width, height = image.size
            images.append({
                "category": category,
                "src": relative_path,
                "hasDescription": path.with_suffix(".md").is_file(),
                "title": path.stem,
                "width": width,
                "height": height,
            })
            counts[category] += 1

    images.sort(key=lambda image: hashlib.sha256(str(image["src"]).encode("utf-8")).hexdigest())
    return images, {
        "total_categorized": len(images),
        "category_counts": counts,
        "skipped": skipped,
    }


def write_if_changed(path: Path, content: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.write_text(content, encoding="utf-8")
    return True


def main() -> None:
    images, report = scan_images()
    data_path = SITE_DIR / "scripts" / "gallery-data.js"
    marker = "// Runtime gallery2 loader\n"
    _, separator, loader = data_path.read_text(encoding="utf-8").partition(marker)
    if not separator:
        raise RuntimeError(f"Missing runtime loader in {data_path}")
    data = "window.__GALLERY_IMAGES__ = " + json.dumps(images, ensure_ascii=False, indent=2)
    data += ";\n\n" + marker + loader

    index_path = SITE_DIR / "index.html"
    html = index_path.read_text(encoding="utf-8")
    version = str(int(time.time()))
    for asset in ("styles/gallery.css", "scripts/gallery-data.js", "scripts/gallery.js"):
        pattern = rf'((?:src|href)=")({re.escape(asset)})(?:\?[^"\']*)?(")'
        html = re.sub(pattern, lambda match: f'{match[1]}{match[2]}?v={version}{match[3]}', html)

    outputs = {
        data_path: data,
        SITE_DIR / "catalog_report.json": json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        index_path: html,
    }
    for path, content in outputs.items():
        action = "Updated" if write_if_changed(path, content) else "Checked"
        print(f"{action} {path.relative_to(SITE_DIR)}.")
    print(f"Gallery 2: {len(images)} images; " + ", ".join(
        f"{category}: {report['category_counts'][category]}" for category in CATEGORIES
    ))


if __name__ == "__main__":
    main()
