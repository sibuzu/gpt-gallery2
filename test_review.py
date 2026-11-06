"""Destructive review operations are tested only inside temporary fixtures."""
import base64
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from review import Reviewer, identity, make_handler, ThreadingHTTPServer
from review_catalog import CATEGORIES, image_path, update_review_catalog, write_json

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aXioAAAAASUVORK5CYII=")


def fixture(site):
    for category in CATEGORIES:
        (site / "images" / category).mkdir(parents=True)
    (site / "imports").mkdir()
    (site / "scripts").mkdir()
    names = [("無重力", "無重力-001", "2026-11-01T08:00:00+08:00"),
             ("無重力", "無重力-002", "2026-11-02T08:00:00+08:00"),
             ("自動", "自動場景-01", "2026-11-04T08:00:00+08:00"),
             ("構圖", "構圖場景-01", "2026-11-05T08:00:00+08:00"),
             ("構圖", "構圖場景-02", "2026-11-05T09:00:00+08:00")]
    records = []
    for category, name, added in names:
        path = site / "images" / category / (name + ".png")
        path.write_bytes(PNG)
        path.with_suffix(".md").write_text("原始 prompt " + name)
        records.append({"category": category, "image": path.relative_to(site).as_posix(),
                        "prompt_file": path.with_suffix(".md").relative_to(site).as_posix(),
                        "imported_at": added, "horizontal_mirror": False})
    write_json(site / "imports/test.json", {"date": "2026-11-05", "images": records,
               "summary": {"source_images": 5, "added": 5, "horizontally_mirrored": 0}})
    snapshot = [{"src": r["image"], "category": r["category"], "hasDescription": True,
                 "title": Path(r["image"]).stem, "width": 1, "height": 1} for r in records]
    (site / "scripts/gallery-data.js").write_text("window.__GALLERY_IMAGES__ = " + json.dumps(snapshot)
                + ";\n\n// Runtime gallery2 loader\nwindow.stub = true;\n")
    write_json(site / "catalog_report.json", {"total_categorized": 5,
               "category_counts": {"無重力": 2, "自動": 1, "構圖": 2}, "skipped": []})
    (site / "index.html").write_text('<script src="scripts/gallery-data.js?v=old"></script>')
    return records


@contextmanager
def serving(reviewer):
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(reviewer, "test-token", "http://127.0.0.1:0"))
    origin = f"http://127.0.0.1:{server.server_port}"
    server.RequestHandlerClass = make_handler(reviewer, "test-token", origin)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield origin
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.site = Path(self.temp.name) / "site"
        self.records = fixture(self.site)
        self.state = Path(self.temp.name) / "progress/state.json"
        self.reviewer = Reviewer(self.site, self.state)

    def tearDown(self):
        self.temp.cleanup()

    def test_dates_remain_stable_and_new_same_day_import_follows_cursor(self):
        images = self.reviewer.view()["images"]
        self.assertEqual([r["date"] for r in images], ["2026-11-01", "2026-11-02", "2026-11-04", "2026-11-05", "2026-11-05"])
        last = images[-1]
        self.reviewer.progress(last["src"], "全部")
        os.utime(self.site / last["src"], (2000000000, 2000000000))
        path = self.site / "images/構圖/新增-01.png"
        path.write_bytes(PNG)
        write_json(self.site / "imports/later.json", {"imported_at": "2026-11-05T20:00:00+08:00",
                   "images": [{"image": "images/構圖/新增-01.png"}]})
        reopened = Reviewer(self.site, self.state).view()
        self.assertEqual(reopened["progress"]["src"], last["src"])
        self.assertEqual(reopened["images"][-1]["src"], "images/構圖/新增-01.png")
        self.assertEqual(reopened["images"][-2]["addedAt"], last["addedAt"])

    def test_missing_import_date_uses_first_git_addition(self):
        path = self.site / "images/無重力/歷史-001.png"
        path.write_bytes(PNG)
        subprocess.run(["git", "init", "-q"], cwd=self.site, check=True)
        subprocess.run(["git", "add", "images/無重力/歷史-001.png"], cwd=self.site, check=True)
        env = {**os.environ, "GIT_AUTHOR_DATE": "2026-10-28T12:00:00+08:00", "GIT_COMMITTER_DATE": "2026-10-28T12:00:00+08:00"}
        subprocess.run(["git", "-c", "user.name=Review Test", "-c", "user.email=review@example.invalid",
                        "commit", "-qm", "Fixture"], cwd=self.site, env=env, check=True)
        item = next(r for r in update_review_catalog(self.site) if r["title"] == "歷史-001")
        self.assertEqual((item["date"], item["dateSource"]), ("2026-10-28", "git"))

    def test_delete_removes_pair_updates_references_and_resumes_successor(self):
        src = self.records[3]["image"]
        path = self.site / src
        before = {str(p.relative_to(self.site)): p.read_bytes() for p in (self.site / "images").rglob("*") if p.is_file()}
        result = self.reviewer.delete(src, identity(path)["signature"], "構圖")
        self.assertFalse(path.exists())
        self.assertFalse(path.with_suffix(".md").exists())
        self.assertEqual(result["progress"]["src"], self.records[4]["image"])
        self.assertEqual(result["deletedByCategory"], {"無重力": 0, "自動": 0, "構圖": 1})
        self.assertEqual(Reviewer(self.site, self.state).view()["progress"]["src"], self.records[4]["image"])
        self.assertEqual(Reviewer(self.site, self.state).view()["deletedByCategory"]["構圖"], 1)
        data = json.loads((self.site / "imports/test.json").read_text())
        self.assertEqual(data["summary"]["added"], 4)
        self.assertEqual(data["removed_after_import"][0]["image"], src)
        self.assertNotIn(src, (self.site / "scripts/gallery-data.js").read_text())
        self.assertEqual(json.loads((self.site / "catalog_report.json").read_text())["total_categorized"], 4)
        remaining = {str(p.relative_to(self.site)): p.read_bytes() for p in (self.site / "images").rglob("*") if p.is_file()}
        del before[src]
        del before[str(Path(src).with_suffix('.md'))]
        self.assertEqual(before, remaining)
        self.assertFalse(list(self.site.rglob("*.bak")))

    def test_changed_prompt_prevents_stale_delete(self):
        path = self.site / self.records[0]["image"]
        signature = identity(path)["signature"]
        path.with_suffix(".md").write_text("changed prompt")
        with self.assertRaisesRegex(ValueError, "已改變"):
            self.reviewer.delete(self.records[0]["image"], signature, "全部")
        self.assertTrue(path.exists())

    def test_scoped_paths_and_symlinks(self):
        for src in ["../secret.png", "images/清新/photo.png", "images/無重力/../構圖/x.png", "/images/無重力/x.png", "images//無重力/x.png"]:
            with self.assertRaises(ValueError):
                image_path(self.site, src)
        path = self.site / self.records[0]["image"]
        outside = Path(self.temp.name) / "outside.md"
        outside.write_text("must remain")
        path.with_suffix(".md").unlink()
        path.with_suffix(".md").symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "符號連結"):
            self.reviewer.detail(self.records[0]["image"])
        self.assertEqual(outside.read_text(), "must remain")

    def test_interrupted_deletion_finishes_after_restart_without_backup(self):
        src = self.records[0]["image"]
        signature = self.reviewer.detail(src)["signature"]
        with patch.object(self.reviewer, "update_gallery", side_effect=OSError("interrupted")):
            with self.assertRaises(OSError):
                self.reviewer.delete(src, signature, "全部")
        self.assertIsNotNone(json.loads(self.state.read_text())["pending"])
        reopened = Reviewer(self.site, self.state)
        self.assertIsNone(reopened.state["pending"])
        data = json.loads((self.site / "imports/test.json").read_text())
        self.assertEqual(len(data["removed_after_import"]), 1)
        self.assertEqual(len(reopened.view()["images"]), 4)
        self.assertEqual(reopened.view()["deletedByCategory"]["無重力"], 1)

    def test_legacy_deleted_counts_include_tracked_deletions_without_double_counting(self):
        subprocess.run(["git", "init", "-q"], cwd=self.site, check=True)
        subprocess.run(["git", "add", "images"], cwd=self.site, check=True)
        subprocess.run(["git", "-c", "user.name=Review Test", "-c", "user.email=review@example.invalid",
                        "commit", "-qm", "Fixture"], cwd=self.site, check=True)
        record = self.records[3]
        path = self.site / record["image"]
        data = json.loads((self.site / "imports/test.json").read_text())
        data["images"].remove(record)
        data["removed_after_import"] = [{**record, "output_sha256": identity(path)["imageHash"],
                                         "reason": "Permanently deleted from REVIEW"}]
        write_json(self.site / "imports/test.json", data)
        for src in (self.records[0]["image"], record["image"]):
            target = self.site / src
            target.unlink()
            target.with_suffix(".md").unlink()
        write_json(self.state, {"category": "全部", "src": self.records[4]["image"], "pending": None})
        migrated = Reviewer(self.site, self.state).view()
        self.assertEqual(migrated["deletedByCategory"], {"無重力": 1, "自動": 0, "構圖": 1})
        self.assertEqual(Reviewer(self.site, self.state).view()["deletedByCategory"], migrated["deletedByCategory"])

    def test_recovery_does_not_delete_replacement_file(self):
        src = self.records[0]["image"]
        path = self.site / src
        self.reviewer.state["pending"] = {"src": src, **identity(path), "date": "2026-11-05", "next": None}
        self.reviewer.save()
        path.write_bytes(b"replacement")
        with self.assertRaisesRegex(ValueError, "已被更換"):
            Reviewer(self.site, self.state)
        self.assertEqual(path.read_bytes(), b"replacement")

    def test_delete_last_image_of_category_leaves_empty_category(self):
        src = self.records[2]["image"]
        result = self.reviewer.delete(src, self.reviewer.detail(src)["signature"], "自動")
        self.assertIsNone(result["progress"]["src"])
        self.assertEqual(result["progress"]["category"], "自動")
        self.assertFalse(any(r["category"] == "自動" for r in result["images"]))

    def test_http_rejects_cross_origin_missing_token_and_wrong_host(self):
        src = self.records[0]["image"]
        body = json.dumps({"src": src, "signature": self.reviewer.detail(src)["signature"], "category": "全部"}).encode()
        with serving(self.reviewer) as origin:
            with urlopen(origin + "/api/catalog") as response:
                self.assertEqual(len(json.load(response)["images"]), 5)
            for headers in [{"Origin": "https://example.invalid", "X-Review-Token": "test-token"},
                            {"Origin": origin},
                            {"Origin": origin, "X-Review-Token": "test-token", "Host": "example.invalid"}]:
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(origin + "/api/delete", data=body, headers=headers))
                self.assertEqual(error.exception.code, 403)
                self.assertTrue((self.site / src).exists())
            with urlopen(Request(origin + "/api/delete", data=body,
                                 headers={"Origin": origin, "X-Review-Token": "test-token"})) as response:
                self.assertEqual(json.load(response)["deleted"], src)


if __name__ == "__main__":
    unittest.main()
