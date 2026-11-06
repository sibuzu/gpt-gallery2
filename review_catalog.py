"""Stable import dates for the three review collections (standard library only)."""
from __future__ import annotations

from datetime import datetime, time, timezone, timedelta
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import tempfile

CATEGORIES = ("無重力", "自動", "構圖")
EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
TAIPEI = timezone(timedelta(hours=8))


def atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, 0o644)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_json(path: Path, data: object) -> None:
    content = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if not path.exists() or path.read_text(encoding="utf-8") != content:
        atomic_text(path, content)


def image_path(site: Path, src: str, *, must_exist: bool = True) -> Path:
    if not isinstance(src, str) or "\\" in src or "\x00" in src:
        raise ValueError("圖片路徑不正確。")
    parts = PurePosixPath(src).parts
    if (len(parts) != 3 or parts[0] != "images" or parts[1] not in CATEGORIES
            or PurePosixPath(src).as_posix() != src or parts[2] in (".", "..")
            or Path(parts[2]).suffix.lower() not in EXTENSIONS):
        raise ValueError("只能操作無重力、自動、構圖的圖片。")
    path = site / src
    if any(p.is_symlink() for p in (site / "images", path.parent, path, path.with_suffix(".md"))):
        raise ValueError("不接受符號連結。")
    if must_exist and not path.is_file():
        raise FileNotFoundError("圖片已不存在，請重新整理清單。")
    return path


def timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        result = result.replace(tzinfo=TAIPEI)
    return result.astimezone(TAIPEI)


def git_dates(site: Path) -> dict[str, str]:
    try:
        result = subprocess.run(
            ["git", "-c", "core.quotePath=false", "log", "--reverse", "--format=@@%cI",
             "--name-only", "--diff-filter=A", "--no-renames", "--",
             *(f"images/{category}" for category in CATEGORIES)],
            cwd=site, capture_output=True, text=True, check=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    dates: dict[str, str] = {}
    current = ""
    for line in result.stdout.splitlines():
        if line.startswith("@@"):
            current = timestamp(line[2:]).isoformat()
        elif line.startswith("images/") and current:
            dates.setdefault(line, current)
    return dates


def update_review_catalog(site: Path) -> list[dict]:
    site = Path(site).resolve()
    target = site / "review-catalog.json"
    previous = {r["src"]: r for r in json.loads(target.read_text())["images"]} if target.exists() else {}
    imports = {}
    for manifest in sorted((site / "imports").glob("*.json")):
        data = json.loads(manifest.read_text(encoding="utf-8"))
        for record in data.get("images", []):
            if not isinstance(record, dict) or not record.get("image"):
                continue
            value = record.get("imported_at") or data.get("imported_at") or data.get("date")
            if value:
                imports.setdefault(record["image"], value)
    history = None
    images = []
    for category in CATEGORIES:
        folder = site / "images" / category
        if not folder.is_dir() or folder.is_symlink():
            raise ValueError(f"找不到一般圖片目錄：{folder}")
        for path in sorted(folder.iterdir()):
            if path.suffix.lower() not in EXTENSIONS or not path.is_file() or path.is_symlink():
                continue
            src = path.relative_to(site).as_posix()
            image_path(site, src)
            old = previous.get(src)
            if old:
                added = timestamp(old["addedAt"])
                source = old["dateSource"]
            else:
                if history is None:
                    history = git_dates(site)
                imported = imports.get(src)
                modified = datetime.fromtimestamp(path.stat().st_mtime, TAIPEI)
                committed = timestamp(history[src]) if src in history else None
                if imported:
                    added = timestamp(imported)
                    if len(imported) == 10:
                        candidate = committed or modified
                        if candidate.date() == added.date():
                            added = candidate
                        else:
                            added = datetime.combine(added.date(), time.min, TAIPEI)
                    source = "import"
                elif committed:
                    added, source = committed, "git"
                else:
                    added, source = modified, "file"
            images.append({"src": src, "category": category, "title": path.stem,
                           "date": added.date().isoformat(), "addedAt": added.isoformat(),
                           "dateSource": source})
    images.sort(key=lambda r: (r["addedAt"], r["src"]))
    write_json(target, {"version": 1, "timezone": "Asia/Taipei", "images": images})
    return images
