import json
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from stylemate.domain.models import FavoriteOutfit, Garment, OutfitFeedback


class SQLiteWardrobeRepository:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connection(self):
        with closing(sqlite3.connect(self.path)) as connection:
            yield connection

    def _initialize(self) -> None:
        with self._connection() as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS garments (
                  owner_id TEXT NOT NULL,
                  garment_id TEXT NOT NULL,
                  image_hash TEXT,
                  payload TEXT NOT NULL,
                  PRIMARY KEY (owner_id, garment_id)
                );
                CREATE INDEX IF NOT EXISTS idx_garment_hash
                  ON garments(owner_id, image_hash);
                CREATE TABLE IF NOT EXISTS profiles (
                  owner_id TEXT PRIMARY KEY,
                  payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS favorites (
                  owner_id TEXT NOT NULL,
                  outfit_id TEXT NOT NULL,
                  payload TEXT NOT NULL,
                  PRIMARY KEY (owner_id, outfit_id)
                );
                CREATE TABLE IF NOT EXISTS feedback (
                  owner_id TEXT NOT NULL,
                  outfit_id TEXT NOT NULL,
                  payload TEXT NOT NULL,
                  PRIMARY KEY (owner_id, outfit_id)
                );
                CREATE TABLE IF NOT EXISTS app_metadata (
                  metadata_key TEXT PRIMARY KEY,
                  metadata_value TEXT NOT NULL
                );
                """
            )

    def get_metadata(self, key: str) -> str | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT metadata_value FROM app_metadata WHERE metadata_key = ?",
                (key,),
            ).fetchone()
        return row[0] if row else None

    def set_metadata(self, key: str, value: str) -> None:
        with self._connection() as connection, connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO app_metadata (metadata_key, metadata_value)
                VALUES (?, ?)
                """,
                (key, value),
            )

    @staticmethod
    def _serialize(model) -> str:
        return json.dumps(model.model_dump(mode="json"), ensure_ascii=False)

    def list_garments(self, owner_id: str) -> list[Garment]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT payload FROM garments WHERE owner_id = ? ORDER BY rowid",
                (owner_id,),
            ).fetchall()
        return [Garment.model_validate_json(payload) for (payload,) in rows]

    def get_garment(self, owner_id: str, garment_id: str) -> Garment | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT payload FROM garments WHERE owner_id = ? AND garment_id = ?",
                (owner_id, garment_id),
            ).fetchone()
        return Garment.model_validate_json(row[0]) if row else None

    def save_garment(self, owner_id: str, garment: Garment) -> None:
        with self._connection() as connection, connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO garments (owner_id, garment_id, image_hash, payload)
                VALUES (?, ?, ?, ?)
                """,
                (owner_id, garment.id, garment.image_hash, self._serialize(garment)),
            )

    def delete_garment(self, owner_id: str, garment_id: str) -> None:
        with self._connection() as connection, connection:
            connection.execute(
                "DELETE FROM garments WHERE owner_id = ? AND garment_id = ?",
                (owner_id, garment_id),
            )

    def find_garment_by_hash(self, owner_id: str, image_hash: str) -> Garment | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT payload FROM garments
                WHERE owner_id = ? AND image_hash = ?
                ORDER BY rowid LIMIT 1
                """,
                (owner_id, image_hash),
            ).fetchone()
        return Garment.model_validate_json(row[0]) if row else None

    def get_profile(self, owner_id: str) -> dict[str, str]:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT payload FROM profiles WHERE owner_id = ?", (owner_id,)
            ).fetchone()
        return json.loads(row[0]) if row else {}

    def save_profile(self, owner_id: str, profile: dict[str, str]) -> None:
        payload = json.dumps(profile, ensure_ascii=False)
        with self._connection() as connection, connection:
            connection.execute(
                "INSERT OR REPLACE INTO profiles (owner_id, payload) VALUES (?, ?)",
                (owner_id, payload),
            )

    def save_favorite(self, favorite: FavoriteOutfit) -> None:
        with self._connection() as connection, connection:
            connection.execute(
                "INSERT OR REPLACE INTO favorites (owner_id, outfit_id, payload) VALUES (?, ?, ?)",
                (
                    favorite.owner_id,
                    favorite.recommendation.id,
                    self._serialize(favorite),
                ),
            )

    def list_favorites(self, owner_id: str) -> list[FavoriteOutfit]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT payload FROM favorites WHERE owner_id = ? ORDER BY rowid",
                (owner_id,),
            ).fetchall()
        return [FavoriteOutfit.model_validate_json(payload) for (payload,) in rows]

    def delete_favorite(self, owner_id: str, outfit_id: str) -> None:
        with self._connection() as connection, connection:
            connection.execute("DELETE FROM favorites WHERE owner_id = ? AND outfit_id = ?", (owner_id, outfit_id))

    def save_feedback(self, feedback: OutfitFeedback) -> None:
        with self._connection() as connection, connection:
            connection.execute(
                "INSERT OR REPLACE INTO feedback (owner_id, outfit_id, payload) VALUES (?, ?, ?)",
                (feedback.owner_id, feedback.outfit_id, self._serialize(feedback)),
            )
