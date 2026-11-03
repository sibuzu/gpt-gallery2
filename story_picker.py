#!/usr/bin/env python3
"""Compare numbered story A/B pairs and move the preferred pair into 故事/."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import struct
import tempfile
import threading
import time
from urllib.parse import urlsplit
import webbrowser

SITE = Path(__file__).resolve().parent
FOLDERS = ("故事", "故事2")
NAME = re.compile(r"^(\d{3})([AB])_.+\.png$")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Picker:
    def __init__(self, site, state_path):
        self.site = Path(site).resolve()
        self.state_path = Path(state_path)
        self.mutex = threading.RLock()
        self.state = {"current": None, "choices": {}, "revision": 0, "pending": None}
        if self.state_path.exists():
            self.state = json.loads(self.state_path.read_text())
        for folder in FOLDERS:
            directory = self.site / "images" / folder
            if not directory.is_dir() or directory.is_symlink():
                raise ValueError(f"找不到圖片目錄：{directory}")
        self.recover()
        pairs = self.scan()
        if not self.state_path.exists():
            self.state["current"] = min(pairs) if pairs else None
            self.save()

    def save(self):
        atomic_text(self.state_path, json.dumps(self.state, ensure_ascii=False, indent=2) + "\n")

    def scan(self):
        pairs = {}
        for folder in FOLDERS:
            for path in sorted((self.site / "images" / folder).glob("*.png")):
                match = NAME.fullmatch(path.name)
                if not match:
                    continue
                number, letter = int(match[1]), match[2]
                if path.is_symlink() or path.with_suffix(".md").is_symlink():
                    raise ValueError(f"不接受符號連結：{path.name}")
                if not path.with_suffix(".md").is_file():
                    raise ValueError(f"缺少提示詞：{path.with_suffix('.md').name}")
                pair = pairs.setdefault(number, {})
                if letter in pair:
                    raise ValueError(f"{number:03d}{letter} 有多張圖片，請先整理再繼續。")
                pair[letter] = path
        for number, pair in pairs.items():
            if set(pair) != {"A", "B"}:
                raise ValueError(f"{number:03d} 缺少 A 或 B 圖片。")
        return pairs

    def pair_signature(self, pair):
        return hashlib.sha256("|".join(
            str(path.relative_to(self.site)) + ":" + digest(path)
            for letter in ("A", "B")
            for path in (pair[letter], pair[letter].with_suffix(".md"))
        ).encode()).hexdigest()

    def view(self):
        if self.state.get("pending"):
            self.recover()
        pairs = self.scan()
        number = self.state["current"]
        result = {"revision": self.state["revision"], "number": number,
                  "numbers": sorted(pairs), "total": len(pairs),
                  "completed": sum(str(n) in self.state["choices"] for n in pairs),
                  "chosen": self.state["choices"].get(str(number)), "cards": []}
        if number is None:
            return result
        if number not in pairs:
            raise ValueError("目前編號已不存在，請重新啟動工具。")
        pair = pairs[number]
        result["signature"] = self.pair_signature(pair)
        for letter in ("A", "B"):
            path = pair[letter]
            result["cards"].append({"letter": letter, "name": path.name,
                                    "folder": path.parent.name,
                                    "image": f"/image/{number}/{letter}?v={result['signature']}"})
        return result

    def jump(self, number, revision):
        if revision != self.state["revision"]:
            raise ValueError("頁面已更新，請重新整理後操作。")
        if type(number) is not int or number not in self.scan():
            raise ValueError("請輸入清單中存在的編號。")
        self.state["current"] = number
        self.state["revision"] += 1
        self.save()
        return self.view()

    def choose(self, letter, revision, signature):
        if self.state.get("pending"):
            self.recover()
            raise ValueError("已完成上次移動，請重新整理後繼續。")
        if revision != self.state["revision"]:
            raise ValueError("這個選擇已過期，請重新整理頁面。")
        number = self.state["current"]
        pairs = self.scan()
        if letter not in ("A", "B") or number not in pairs:
            raise ValueError("沒有可選擇的圖片。")
        pair = pairs[number]
        if not secrets.compare_digest(signature, self.pair_signature(pair)):
            raise ValueError("圖片或提示詞已被其他程式更新，請重新整理後選擇。")
        moves = []
        for candidate in ("A", "B"):
            folder = "故事" if candidate == letter else "故事2"
            for source in (pair[candidate], pair[candidate].with_suffix(".md")):
                target = self.site / "images" / folder / source.name
                if target == source:
                    continue
                if target.exists() or target.is_symlink():
                    raise ValueError(f"目的地已有同名檔案：{target.name}")
                moves.append({"source": str(source.relative_to(self.site)),
                              "target": str(target.relative_to(self.site)), "sha256": digest(source)})
        numbers = sorted(pairs)
        index = numbers.index(number) + 1
        self.state["pending"] = {"number": number, "letter": letter, "moves": moves,
                                 "next": numbers[index] if index < len(numbers) else None}
        self.save()
        self.recover()
        return self.view()

    def recover(self):
        pending = self.state.get("pending")
        if not pending:
            return
        for move in pending["moves"]:
            source = self.site / move["source"]
            target = self.site / move["target"]
            for path in (source, target):
                if path.parent not in [self.site / "images" / folder for folder in FOLDERS]:
                    raise ValueError("移動紀錄包含不允許的路徑。")
                if path.is_symlink():
                    raise ValueError("移動紀錄中的檔案已變成符號連結。")
            if source.name != target.name:
                raise ValueError("移動紀錄不可修改檔名。")
            if target.exists():
                if digest(target) != move["sha256"]:
                    raise ValueError(f"目的地檔案已變更：{target.name}")
                if source.exists():
                    if not os.path.samefile(source, target):
                        raise ValueError(f"目的地已有另一個同名檔案：{target.name}")
                    source.unlink()
            else:
                if not source.is_file() or digest(source) != move["sha256"]:
                    raise ValueError(f"來源檔案已變更：{source.name}")
                # A hard link followed by unlink moves the original inode without
                # copying bytes or overwriting an independently created target.
                os.link(source, target)
                source.unlink()
        self.refresh_catalog()
        self.state["choices"][str(pending["number"])] = pending["letter"]
        self.state["current"] = pending["next"]
        self.state["revision"] += 1
        self.state["pending"] = None
        self.save()

    def refresh_catalog(self):
        data_path = self.site / "scripts" / "gallery-data.js"
        marker = "// Runtime gallery2 loader\n"
        snapshot, separator, loader = data_path.read_text().partition(marker)
        if not separator:
            raise ValueError("圖庫索引格式不正確。")
        images = json.loads(snapshot.split(" = ", 1)[1].strip().removesuffix(";"))
        images = [item for item in images if item["category"] not in FOLDERS]
        for folder in FOLDERS:
            for path in sorted((self.site / "images" / folder).glob("*.png")):
                with path.open("rb") as image_file:
                    header = image_file.read(24)
                if header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
                    raise ValueError(f"不是有效的 PNG：{path.name}")
                width, height = struct.unpack(">II", header[16:24])
                images.append({"category": folder, "src": str(path.relative_to(self.site)),
                               "hasDescription": path.with_suffix(".md").is_file(),
                               "title": path.stem, "width": width, "height": height})
        images.sort(key=lambda item: hashlib.sha256(item["src"].encode()).hexdigest())
        atomic_text(data_path, "window.__GALLERY_IMAGES__ = " + json.dumps(images, ensure_ascii=False, indent=2)
                    + ";\n\n" + marker + loader)
        report_path = self.site / "catalog_report.json"
        report = json.loads(report_path.read_text())
        report["total_categorized"] = len(images)
        report["category_counts"] = {category: sum(i["category"] == category for i in images)
                                     for category in report["category_counts"]}
        atomic_text(report_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        index_path = self.site / "index.html"
        html = index_path.read_text()
        for asset in ("styles/gallery.css", "scripts/gallery-data.js", "scripts/gallery.js"):
            html = re.sub(rf'((?:src|href)="{re.escape(asset)})(?:\?[^"\']*)?(")',
                          lambda m: f'{m[1]}?v={time.time_ns()}{m[2]}', html)
        atomic_text(index_path, html)


def make_handler(picker, token, origin):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, status, body, content_type="application/json; charset=utf-8"):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def valid_host(self):
            return self.headers.get("Host") == urlsplit(origin).netloc

        def do_GET(self):
            if not self.valid_host():
                return self.respond(403, {"error": "不允許的主機。"})
            path = urlsplit(self.path).path
            try:
                with picker.mutex:
                    if path == "/":
                        html = (SITE / "story_picker.html").read_text().replace("__TOKEN__", token)
                        return self.respond(200, html.encode(), "text/html; charset=utf-8")
                    if path == "/api/state":
                        return self.respond(200, picker.view())
                    match = re.fullmatch(r"/image/(\d{1,3})/([AB])", path)
                    if match:
                        image = picker.scan()[int(match[1])][match[2]]
                        return self.respond(200, image.read_bytes(), "image/png")
                self.respond(404, {"error": "找不到頁面。"})
            except (ValueError, OSError, KeyError) as error:
                self.respond(409, {"error": str(error)})

        def do_POST(self):
            if (not self.valid_host() or self.headers.get("Origin") != origin
                    or not secrets.compare_digest(self.headers.get("X-Picker-Token", ""), token)):
                return self.respond(403, {"error": "請從本機工具頁面操作。"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 4096:
                    raise ValueError("請求大小不正確。")
                body = json.loads(self.rfile.read(length))
                with picker.mutex:
                    path = urlsplit(self.path).path
                    if path == "/api/jump":
                        result = picker.jump(body["number"], body["revision"])
                    elif path == "/api/choose":
                        result = picker.choose(body["letter"], body["revision"], body["signature"])
                    else:
                        return self.respond(404, {"error": "找不到操作。"})
                self.respond(200, result)
            except (ValueError, OSError, KeyError, TypeError) as error:
                self.respond(409, {"error": str(error)})
    return Handler


def main():
    parser = argparse.ArgumentParser(description="逐號比較故事 A/B，點選的圖與提示詞移到故事/。")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    identity = hashlib.sha256(str(SITE).encode()).hexdigest()[:16]
    state_dir = Path.home() / ".local/share/gpt-gallery/story-picker" / identity
    state_dir.mkdir(parents=True, exist_ok=True)
    with (state_dir / "state.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("故事挑選工具已在執行中。")
        picker = Picker(SITE, state_dir / "state.json")
        server = ThreadingHTTPServer(("127.0.0.1", args.port), BaseHTTPRequestHandler)
        origin = f"http://127.0.0.1:{server.server_port}"
        server.RequestHandlerClass = make_handler(picker, secrets.token_hex(24), origin)
        print(f"故事挑選工具：{origin}\n進度檔：{picker.state_path}", flush=True)
        if not args.no_browser:
            webbrowser.open(origin)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


if __name__ == "__main__":
    main()
