"""Shared, durable snapshots of the board's pixel drawings."""

from contextlib import closing, contextmanager
from pathlib import Path
import sqlite3

from drawing import validate_pixels


class SceneStorageError(RuntimeError):
    pass


class SceneStore:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def _connection(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Each request owns its connection; SQLite serializes concurrent saves.
            with closing(sqlite3.connect(str(self.path), timeout=5)) as connection:
                connection.row_factory = sqlite3.Row
                with connection:
                    connection.execute("""
                        CREATE TABLE IF NOT EXISTS scenes (
                            id INTEGER PRIMARY KEY,
                            pixels TEXT NOT NULL UNIQUE,
                            created_at TEXT NOT NULL DEFAULT
                                (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                        )
                    """)
                    yield connection
        except (OSError, sqlite3.Error) as error:
            raise SceneStorageError("Saved scenes are unavailable. Try again.") from error

    @staticmethod
    def _scene(row):
        if row is None:
            return None
        try:
            validate_pixels(row["pixels"])
        except ValueError as error:
            raise SceneStorageError("This saved scene is damaged and cannot be played.") from error
        return dict(row)

    def list(self):
        with self._connection() as connection:
            return [self._scene(row) for row in connection.execute(
                "SELECT id, pixels, created_at FROM scenes ORDER BY id DESC")]

    def get(self, scene_id):
        if not 0 < scene_id <= 2 ** 63 - 1:
            return None
        with self._connection() as connection:
            return self._scene(connection.execute(
                "SELECT id, pixels, created_at FROM scenes WHERE id = ?", (scene_id,)
            ).fetchone())

    def save(self, pixels):
        pixels = validate_pixels(pixels)
        with self._connection() as connection:
            # Retrying a save, including after a lost response, reuses the snapshot.
            inserted = connection.execute(
                "INSERT INTO scenes (pixels) VALUES (?) ON CONFLICT(pixels) DO NOTHING",
                (pixels,),
            ).rowcount == 1
            scene = self._scene(connection.execute(
                "SELECT id, pixels, created_at FROM scenes WHERE pixels = ?", (pixels,)
            ).fetchone())
            return scene, inserted
