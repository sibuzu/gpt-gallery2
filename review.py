#!/usr/bin/env python3
"""Local chronological image review with permanent, scoped deletion."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import fcntl
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import secrets
import subprocess
import threading
from urllib.parse import parse_qs, quote, unquote, urlsplit
import webbrowser

from review_catalog import CATEGORIES, EXTENSIONS, TAIPEI, atomic_text, image_path, update_review_catalog, write_json

SITE = Path(__file__).resolve().parent
ASSETS = {"/scripts/review.js": "text/javascript; charset=utf-8",
          "/styles/review.css": "text/css; charset=utf-8", "/favorit.ico": "image/x-icon"}
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".webp": "image/webp", ".gif": "image/gif"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(path: Path) -> dict:
    prompt = path.with_suffix(".md")
    hashes = {"imageHash": digest(path), "promptHash": digest(prompt) if prompt.is_file() else None}
    hashes["signature"] = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    return hashes


class Reviewer:
    def __init__(self, site: Path, state_path: Path):
        self.site = Path(site).resolve()
        self.state_path = Path(state_path)
        self.mutex = threading.RLock()
        self.state = {"src": None, "date": None, "addedAt": None, "category": "全部", "pending": None}
        if self.state_path.exists():
            self.state.update(json.loads(self.state_path.read_text(encoding="utf-8")))
        if "deletedByCategory" not in self.state:
            self.state["deletedByCategory"] = self.previous_deletions()
        self.recover()

    def previous_deletions(self):
        """Migrate the deletions made before persistent review counters existed."""
        removed = set()
        pending = self.state.get("pending") or {}
        for manifest in (self.site / "imports").glob("*.json"):
            data = json.loads(manifest.read_text(encoding="utf-8"))
            for record in data.get("removed_after_import", []):
                if not isinstance(record, dict) or "REVIEW" not in record.get("reason", ""):
                    continue
                src = record.get("image", "")
                try:
                    image_path(self.site, src, must_exist=False)
                except ValueError:
                    continue
                fingerprint = record.get("output_sha256") or record.get("source_file_id") or ""
                if src == pending.get("src") and fingerprint == pending.get("imageHash"):
                    continue
                removed.add((src, fingerprint))
        known = {src for src, _ in removed}
        try:
            tracked = subprocess.run(["git", "ls-files", "-z", "--",
                                      *(f"images/{c}" for c in CATEGORIES)], cwd=self.site,
                                     capture_output=True, text=True, check=True, timeout=10).stdout.split("\0")
        except (OSError, subprocess.SubprocessError):
            tracked = []
        for src in tracked:
            if (Path(src).suffix.lower() in EXTENSIONS and src not in known
                    and src != pending.get("src") and not (self.site / src).exists()):
                removed.add((src, "tracked-deletion"))
        counts = Counter(src.split("/")[1] for src, _ in removed)
        return {category: counts[category] for category in CATEGORIES}

    def save(self):
        write_json(self.state_path, self.state)

    def records(self):
        return update_review_catalog(self.site)

    def selected(self, records):
        category = self.state["category"]
        return [r for r in records if category == "全部" or r["category"] == category]

    def remember(self, record):
        self.state.update({key: record[key] for key in ("src", "date", "addedAt")})

    def view(self):
        records = self.records()
        selected = self.selected(records)
        current = next((r for r in selected if r["src"] == self.state["src"]), None)
        if current is None and selected:
            anchor = (self.state.get("addedAt") or "", self.state.get("src") or "")
            current = next((r for r in selected if (r["addedAt"], r["src"]) >= anchor), selected[-1])
        if current:
            self.remember(current)
        else:
            self.state["src"] = None
        self.save()
        for record in records:
            path = image_path(self.site, record["src"])
            stat = path.stat()
            record["imageUrl"] = "/media/" + quote(record["src"].removeprefix("images/"), safe="/")
            record["imageUrl"] += f"?v={stat.st_mtime_ns}-{stat.st_size}"
        return {"images": records, "deletedByCategory": dict(self.state["deletedByCategory"]),
                "progress": {k: v for k, v in self.state.items() if k not in ("pending", "deletedByCategory")}}

    def progress(self, src, category):
        if category not in ("全部", *CATEGORIES):
            raise ValueError("分類不正確。")
        if src is None and not any(category == "全部" or r["category"] == category for r in self.records()):
            self.state.update(category=category, src=None)
            self.save()
            return {"saved": True, "src": None, "date": self.state.get("date")}
        record = next((r for r in self.records() if r["src"] == src), None)
        if record is None or (category != "全部" and record["category"] != category):
            raise ValueError("圖片不在目前分類，請重新整理。")
        self.state["category"] = category
        self.remember(record)
        self.save()
        return {"saved": True, "src": src, "date": record["date"]}

    def detail(self, src):
        path = image_path(self.site, src)
        prompt = path.with_suffix(".md")
        return {**identity(path), "prompt": prompt.read_text(encoding="utf-8") if prompt.is_file() else ""}

    def delete(self, src, signature, category):
        if category not in ("全部", *CATEGORIES):
            raise ValueError("分類不正確。")
        path = image_path(self.site, src)
        actual = identity(path)
        if not isinstance(signature, str) or not secrets.compare_digest(signature, actual["signature"]):
            raise ValueError("圖片或 prompt 已改變，請重新整理後再刪除。")
        records = self.records()
        selected = [r for r in records if category == "全部" or r["category"] == category]
        position = next((i for i, r in enumerate(selected) if r["src"] == src), None)
        if position is None:
            raise ValueError("圖片不在目前分類。")
        remaining = selected[:position] + selected[position + 1:]
        successor = remaining[min(position, len(remaining) - 1)] if remaining else None
        self.state["category"] = category
        self.state["pending"] = {"src": src, **actual,
                                 "next": successor, "date": datetime.now(TAIPEI).isoformat()}
        # Metadata-only journal: a restart can finish interrupted deletion. No image/prompt copies.
        self.save()
        self.recover()
        return {**self.view(), "deleted": src}

    def recover(self):
        pending = self.state.get("pending")
        if not pending:
            return
        path = image_path(self.site, pending["src"], must_exist=False)
        prompt = path.with_suffix(".md")
        # Check both before removing either; never delete a replacement after an interrupted request.
        for target, expected in ((path, pending["imageHash"]), (prompt, pending["promptHash"])):
            if target.exists() and (expected is None or digest(target) != expected):
                raise ValueError(f"待刪檔案已被更換，已停止刪除：{target.name}")
        path.unlink(missing_ok=True)
        prompt.unlink(missing_ok=True)
        self.update_imports(pending)
        self.update_gallery()
        if pending["next"]:
            self.remember(pending["next"])
        else:
            self.state["src"] = None
        category = Path(pending["src"]).parts[1]
        self.state["deletedByCategory"][category] = self.state["deletedByCategory"].get(category, 0) + 1
        self.state["pending"] = None
        self.save()

    def update_imports(self, pending):
        for manifest in (self.site / "imports").glob("*.json"):
            data = json.loads(manifest.read_text(encoding="utf-8"))
            records = data.get("images", [])
            removed = [r for r in records if isinstance(r, dict) and r.get("image") == pending["src"]]
            if not removed:
                continue
            data["images"] = [r for r in records if r not in removed]
            history = data.setdefault("removed_after_import", [])
            for record in removed:
                history.append({**record, "removed_on": pending["date"],
                                "reason": "Permanently deleted with matching prompt from REVIEW at user request."})
            summary = data.setdefault("summary", {})
            summary["added"] = len(data["images"])
            summary["added_by_category"] = dict(Counter(r.get("category", "") for r in data["images"]))
            if "horizontally_mirrored" in summary:
                summary["horizontally_mirrored"] = sum(bool(r.get("horizontal_mirror")) for r in data["images"])
            summary["removed_after_import"] = len(history)
            write_json(manifest, data)

    def update_gallery(self):
        data_path = self.site / "scripts/gallery-data.js"
        if not data_path.exists():
            return
        raw, marker, loader = data_path.read_text(encoding="utf-8").partition("// Runtime gallery2 loader\n")
        match = re.fullmatch(r"window\.__GALLERY_IMAGES__ = (.*);\s*", raw, re.S)
        if not marker or not match:
            raise ValueError("圖庫索引格式不正確；刪除已記錄，修復索引後重啟可完成更新。")
        records = [r for r in json.loads(match[1]) if (self.site / r["src"]).is_file()]
        atomic_text(data_path, "window.__GALLERY_IMAGES__ = " + json.dumps(records, ensure_ascii=False, indent=2)
                    + ";\n\n" + marker + loader)
        report_path = self.site / "catalog_report.json"
        if report_path.exists():
            report = json.loads(report_path.read_text())
            counts = Counter(r["category"] for r in records)
            report["total_categorized"] = len(records)
            report["category_counts"] = {c: counts[c] for c in report["category_counts"]}
            report["skipped"] = [r for r in report.get("skipped", []) if (self.site / r["path"]).is_file()]
            write_json(report_path, report)
        index = self.site / "index.html"
        if index.exists():
            version = str(int(datetime.now().timestamp() * 1000))
            html = re.sub(r'((?:src|href)="(?:styles/gallery\.css|scripts/gallery(?:-data)?\.js))\?[^"\']*(")',
                          lambda m: f'{m[1]}?v={version}{m[2]}', index.read_text())
            atomic_text(index, html)


def make_handler(reviewer: Reviewer, token: str, origin: str):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, status, body, content_type="application/json; charset=utf-8", cache=False):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "private, max-age=86400" if cache else "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def valid_host(self):
            return self.headers.get("Host") == urlsplit(origin).netloc

        def do_GET(self):
            if not self.valid_host():
                return self.respond(403, {"error": "不允許的主機。"})
            url = urlsplit(self.path)
            path = unquote(url.path)
            try:
                with reviewer.mutex:
                    if path in ("/", "/review.html"):
                        html = (SITE / "review.html").read_text().replace("__REVIEW_TOKEN__", token)
                        return self.respond(200, html.encode(), "text/html; charset=utf-8")
                    if path in ASSETS:
                        return self.respond(200, (SITE / path[1:]).read_bytes(), ASSETS[path])
                    if path == "/api/catalog":
                        return self.respond(200, reviewer.view())
                    if path == "/api/item":
                        return self.respond(200, reviewer.detail(parse_qs(url.query)["src"][0]))
                    if path.startswith("/media/"):
                        image = image_path(reviewer.site, "images/" + path.removeprefix("/media/"))
                        return self.respond(200, image.read_bytes(), IMAGE_TYPES[image.suffix.lower()], cache=True)
                self.respond(404, {"error": "找不到頁面。"})
            except (ValueError, OSError, KeyError, TypeError) as error:
                self.respond(409, {"error": str(error)})

        def do_POST(self):
            if (not self.valid_host() or self.headers.get("Origin") != origin
                    or not secrets.compare_digest(self.headers.get("X-Review-Token", ""), token)):
                return self.respond(403, {"error": "請從本機 REVIEW 頁面操作。"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 8192:
                    raise ValueError("請求大小不正確。")
                body = json.loads(self.rfile.read(length))
                with reviewer.mutex:
                    if reviewer.state.get("pending"):
                        reviewer.recover()
                    path = urlsplit(self.path).path
                    if path == "/api/progress":
                        result = reviewer.progress(body["src"], body["category"])
                    elif path == "/api/delete":
                        result = reviewer.delete(body["src"], body["signature"], body["category"])
                    else:
                        return self.respond(404, {"error": "找不到操作。"})
                self.respond(200, result)
            except (ValueError, OSError, KeyError, TypeError) as error:
                self.respond(409, {"error": str(error)})
    return Handler


def main():
    parser = argparse.ArgumentParser(description="依匯入日期檢查無重力、自動、構圖；可直接永久刪圖。")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    key = hashlib.sha256(str(SITE).encode()).hexdigest()[:16]
    state_dir = Path.home() / ".local/share/gpt-gallery/review" / key
    state_dir.mkdir(parents=True, exist_ok=True)
    with (state_dir / "state.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("REVIEW 已在執行中。")
        reviewer = Reviewer(SITE, state_dir / "state.json")
        reviewer.view()
        server = ThreadingHTTPServer(("127.0.0.1", args.port), BaseHTTPRequestHandler)
        origin = f"http://127.0.0.1:{server.server_port}"
        server.RequestHandlerClass = make_handler(reviewer, secrets.token_hex(24), origin)
        print(f"REVIEW：{origin}/review.html\n進度檔：{reviewer.state_path}", flush=True)
        if not args.no_browser:
            webbrowser.open(origin + "/review.html")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


if __name__ == "__main__":
    main()
