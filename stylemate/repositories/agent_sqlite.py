import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path

from stylemate.domain.models import ConversationState, PendingAction, UserDocument


class SQLiteAgentRepository:
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
                CREATE TABLE IF NOT EXISTS agent_conversations (
                  owner_id TEXT NOT NULL,
                  conversation_id TEXT NOT NULL,
                  payload TEXT NOT NULL,
                  PRIMARY KEY (owner_id, conversation_id)
                );
                CREATE TABLE IF NOT EXISTS agent_pending_actions (
                  owner_id TEXT NOT NULL,
                  conversation_id TEXT NOT NULL,
                  payload TEXT NOT NULL,
                  PRIMARY KEY (owner_id, conversation_id)
                );
                CREATE TABLE IF NOT EXISTS agent_documents (
                  owner_id TEXT NOT NULL,
                  conversation_id TEXT NOT NULL,
                  document_id TEXT NOT NULL,
                  payload TEXT NOT NULL,
                  PRIMARY KEY (owner_id, conversation_id, document_id)
                );
                """
            )

    @staticmethod
    def _serialize(model) -> str:
        return json.dumps(model.model_dump(mode="json"), ensure_ascii=False)

    def load_conversation(self, owner_id: str, conversation_id: str) -> ConversationState:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT payload FROM agent_conversations
                WHERE owner_id = ? AND conversation_id = ?
                """,
                (owner_id, conversation_id),
            ).fetchone()
        if row:
            return ConversationState.model_validate_json(row[0])
        return ConversationState(owner_id=owner_id, conversation_id=conversation_id)

    def save_conversation(self, state: ConversationState) -> None:
        with self._connection() as connection, connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO agent_conversations
                (owner_id, conversation_id, payload) VALUES (?, ?, ?)
                """,
                (state.owner_id, state.conversation_id, self._serialize(state)),
            )

    def list_conversations(self, owner_id: str) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT payload FROM agent_conversations
                WHERE owner_id = ?
                """,
                (owner_id,),
            ).fetchall()
        states = [ConversationState.model_validate_json(payload) for (payload,) in rows]
        return sorted(
            (_conversation_summary(state) for state in states),
            key=lambda item: item["last_message_at"],
            reverse=True,
        )

    def clear_conversation(self, owner_id: str, conversation_id: str) -> None:
        with self._connection() as connection, connection:
            connection.execute(
                """
                DELETE FROM agent_conversations
                WHERE owner_id = ? AND conversation_id = ?
                """,
                (owner_id, conversation_id),
            )

    def save_pending(self, action: PendingAction) -> None:
        with self._connection() as connection, connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO agent_pending_actions
                (owner_id, conversation_id, payload) VALUES (?, ?, ?)
                """,
                (action.owner_id, action.conversation_id, self._serialize(action)),
            )

    def get_pending(self, owner_id: str, conversation_id: str) -> PendingAction | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT payload FROM agent_pending_actions
                WHERE owner_id = ? AND conversation_id = ?
                """,
                (owner_id, conversation_id),
            ).fetchone()
        if not row:
            return None
        action = PendingAction.model_validate_json(row[0])
        if action.expires_at <= datetime.now(action.expires_at.tzinfo):
            self.clear_pending(owner_id, conversation_id)
            return None
        return action

    def clear_pending(self, owner_id: str, conversation_id: str) -> None:
        with self._connection() as connection, connection:
            connection.execute(
                """
                DELETE FROM agent_pending_actions
                WHERE owner_id = ? AND conversation_id = ?
                """,
                (owner_id, conversation_id),
            )

    def save_document(self, document: UserDocument) -> None:
        with self._connection() as connection, connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO agent_documents
                (owner_id, conversation_id, document_id, payload) VALUES (?, ?, ?, ?)
                """,
                (
                    document.owner_id,
                    document.conversation_id,
                    document.document_id,
                    self._serialize(document),
                ),
            )

    def list_documents(self, owner_id: str, conversation_id: str) -> list[UserDocument]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT payload FROM agent_documents
                WHERE owner_id = ? AND conversation_id = ?
                ORDER BY rowid
                """,
                (owner_id, conversation_id),
            ).fetchall()
        return [UserDocument.model_validate_json(payload) for (payload,) in rows]

    def delete_document(
        self, owner_id: str, conversation_id: str, document_id: str
    ) -> None:
        with self._connection() as connection, connection:
            connection.execute(
                """
                DELETE FROM agent_documents
                WHERE owner_id = ? AND conversation_id = ? AND document_id = ?
                """,
                (owner_id, conversation_id, document_id),
            )

    def clear_documents(self, owner_id: str, conversation_id: str) -> None:
        with self._connection() as connection, connection:
            connection.execute(
                """
                DELETE FROM agent_documents
                WHERE owner_id = ? AND conversation_id = ?
                """,
                (owner_id, conversation_id),
            )


def _conversation_summary(state: ConversationState) -> dict:
    messages = state.transcript or state.messages
    first_user = next((message.content for message in messages if message.role == "user"), "")
    last_message_at = max(
        (message.created_at for message in messages),
        default=datetime.min,
    )
    return {
        "conversation_id": state.conversation_id,
        "title": (first_user.strip()[:28] or "新对话"),
        "message_count": len(messages),
        "last_message_at": last_message_at,
    }
