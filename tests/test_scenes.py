from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import importlib.util
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from werkzeug.security import generate_password_hash
from werkzeug.test import Client
from werkzeug.wrappers import Response

APP_ROOT = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_ROOT))
from browser_access import PasswordGate
from scenes import SceneStore

spec = importlib.util.spec_from_file_location("scenes_controller", APP_ROOT / "app.py")
controller = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = controller
spec.loader.exec_module(controller)

PIXELS = "1" + "0" * 1023
OTHER_PIXELS = "0" * 1023 + "1"
JSON_HEADERS = {"Accept": "application/json"}


class SceneTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = Path(self.directory.name) / "data" / "scenes.sqlite3"
        controller.app.config.update(TESTING=True, SCENES_DATABASE=self.database)
        controller.current_process = None
        controller.active_script_name = "OFF"
        controller.active_drawing_pixels = None
        controller.switch_lock = threading.Lock()
        self.client = controller.app.test_client()

    def send(self, pixels=PIXELS):
        with patch.object(controller, "launch_mode"):
            response = self.client.post("/drawing", data={"pixels": pixels}, headers=JSON_HEADERS)
        self.assertEqual(response.status_code, 200)

    def save(self, pixels=PIXELS):
        return self.client.post("/scenes", data={"pixels": pixels}, headers=JSON_HEADERS)

    def test_another_client_can_save_the_board_and_replay_after_switching_modes(self):
        self.send()
        other_client = controller.app.test_client()
        preview = other_client.get("/drawing")
        self.assertEqual(preview.get_json(), {"active_script": "Pixel Drawing", "pixels": PIXELS})
        self.assertEqual(preview.headers["Cache-Control"], "no-store")
        process = controller.current_process
        with patch.object(controller, "launch_mode") as launch:
            saved = other_client.post("/scenes", data={"pixels": preview.get_json()["pixels"]})
            launch.assert_not_called()
        self.assertEqual(saved.status_code, 201)
        self.assertIs(controller.current_process, process)
        scene = saved.get_json()["scene"]
        self.assertEqual(scene["pixels"], PIXELS)
        self.assertTrue(scene["created_at"].endswith("Z"))
        self.assertTrue(saved.get_json()["created"])
        with patch.object(controller, "launch_mode") as launch:
            self.client.post("/run", data={"script_name": "Clock"})
            previous = controller.current_process
            response = other_client.post(f"/scenes/{scene['id']}/play")
            launch.assert_called_with("drawing.py", ("--pixels=" + PIXELS,), previous=previous)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"active_script": "Pixel Drawing"})
        self.assertEqual(self.client.get("/drawing").get_json()["pixels"], PIXELS)
        listing = self.client.get("/scenes")
        self.assertEqual(listing.get_json(), {"scenes": [scene]})
        self.assertEqual(listing.headers["Cache-Control"], "no-store")

    def test_invalid_or_stale_previews_do_not_save_or_change_the_board(self):
        self.send()
        with patch.object(controller, "launch_mode") as launch:
            for pixels in ("", "0" * 1023, "0" * 1023 + "x"):
                with self.subTest(pixels=pixels[:10]):
                    self.assertEqual(self.save(pixels).status_code, 400)
            stale = self.save(OTHER_PIXELS)
            self.assertEqual(stale.status_code, 409)
            self.assertIn("changed", stale.get_json()["error"])
            launch.assert_not_called()
        self.assertEqual(self.client.get("/scenes").get_json(), {"scenes": []})
        self.assertEqual(controller.active_drawing_pixels, PIXELS)
        with patch.object(controller, "clear_display"):
            self.client.post("/run", data={"script_name": "OFF"})
        self.assertEqual(self.save().status_code, 409)
        self.assertEqual(self.client.get("/drawing").get_json(), {"active_script": "OFF", "pixels": None})

    def test_completed_drawing_replaces_preview_and_failed_switch_clears_it(self):
        self.send()
        self.send(OTHER_PIXELS)
        self.assertEqual(self.save().status_code, 409)
        self.assertEqual(self.client.get("/drawing").get_json()["pixels"], OTHER_PIXELS)
        scene_id = self.save(OTHER_PIXELS).get_json()["scene"]["id"]
        with patch.object(controller, "launch_mode", side_effect=controller.ModeStartError("Failed")):
            response = self.client.post(f"/scenes/{scene_id}/play")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json()["active_script"], "OFF")
        self.assertEqual(self.client.get("/drawing").get_json()["pixels"], None)

    def test_retries_and_concurrent_saves_preserve_one_persistent_snapshot(self):
        self.send()
        first = self.save()
        second = self.save()
        self.assertEqual(second.status_code, 200)
        self.assertFalse(second.get_json()["created"])
        self.assertEqual(second.get_json()["scene"], first.get_json()["scene"])

        def save(_):
            return SceneStore(self.database).save(OTHER_PIXELS)

        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(save, range(8)))
        self.assertEqual(sum(created for _, created in results), 1)
        self.assertEqual(len({scene["id"] for scene, _ in results}), 1)
        restarted = SceneStore(self.database)
        scenes = restarted.list()
        self.assertEqual([scene["pixels"] for scene in scenes], [OTHER_PIXELS, PIXELS])
        self.assertEqual(restarted.get(first.get_json()["scene"]["id"]), first.get_json()["scene"])

    def test_unavailable_storage_preserves_display_and_existing_database_bytes(self):
        self.send()
        self.database.parent.mkdir(parents=True)
        damaged = b"this is not a sqlite database"
        self.database.write_bytes(damaged)
        previous = controller.current_process
        with patch.object(controller, "launch_mode") as launch:
            for method, url, data in (("get", "/scenes", None), ("post", "/scenes", {"pixels": PIXELS}),
                                      ("post", "/scenes/1/play", None)):
                with self.subTest(method=method, url=url):
                    response = getattr(self.client, method)(url, data=data)
                    self.assertEqual(response.status_code, 503)
                    self.assertIn("error", response.get_json())
            launch.assert_not_called()
        self.assertEqual(self.database.read_bytes(), damaged)
        self.assertIs(controller.current_process, previous)
        self.assertEqual(controller.active_drawing_pixels, PIXELS)
        controller.app.config["SCENES_DATABASE"] = self.database.parent
        self.assertEqual(self.save().status_code, 503)

    def test_missing_and_damaged_scenes_never_launch_a_drawing(self):
        self.send()
        scene_id = self.save().get_json()["scene"]["id"]
        with closing(sqlite3.connect(self.database)) as connection:
            with connection:
                connection.execute("UPDATE scenes SET pixels = ? WHERE id = ?", ("invalid", scene_id))
        previous = controller.current_process
        with patch.object(controller, "launch_mode") as launch:
            for value in (0, scene_id + 1, 10 ** 50):
                self.assertEqual(self.client.post(f"/scenes/{value}/play").status_code, 404)
            self.assertEqual(self.client.post(f"/scenes/{scene_id}/play").status_code, 503)
            launch.assert_not_called()
        self.assertIs(controller.current_process, previous)
        self.assertEqual(controller.active_drawing_pixels, PIXELS)

    def test_public_scene_routes_require_session_and_same_origin_for_commands(self):
        origin = "https://board.example.ts.net"
        password = "test-only-password"
        gate = PasswordGate(controller.app, generate_password_hash(password, method="pbkdf2:sha256:1000"),
                            origin, "test-only-secret-at-least-32-characters")
        public = Client(gate, Response)
        for method, url in (("get", "/scenes"), ("get", "/drawing"), ("post", "/scenes"),
                            ("post", "/scenes/1/play")):
            with self.subTest(method=method, url=url):
                self.assertEqual(getattr(public, method)(url, base_url=origin).status_code, 401)
        self.assertFalse(self.database.exists())
        response = public.post("/login", base_url=origin, data={"password": password}, headers={"Origin": origin})
        self.assertEqual(response.status_code, 303)
        self.assertEqual(public.get("/scenes", base_url=origin).status_code, 200)
        with patch.object(controller, "launch_mode") as launch:
            for url in ("/scenes", "/scenes/1/play"):
                self.assertEqual(public.post(url, base_url=origin, data={"pixels": PIXELS},
                                             headers={"Origin": "https://other.example"}).status_code, 403)
            launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
