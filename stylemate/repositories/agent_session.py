from datetime import datetime

from stylemate.domain.models import ConversationState, PendingAction, UserDocument


class SessionAgentRepository:
    def __init__(self, state: dict):
        agent_state = state.setdefault("stylemate_agent", {})
        # The nested mapping is shared with the UI but is safe to read in tools.
        self.state = {"stylemate_agent": agent_state}

    def _owner(self, owner_id: str) -> dict:
        owner = self.state["stylemate_agent"].setdefault(owner_id, {})
        owner.setdefault("conversations", {})
        owner.setdefault("pending", {})
        owner.setdefault("documents", {})
        return owner

    def load_conversation(self, owner_id: str, conversation_id: str) -> ConversationState:
        payload = self._owner(owner_id)["conversations"].get(conversation_id)
        if payload:
            return ConversationState.model_validate(payload)
        return ConversationState(owner_id=owner_id, conversation_id=conversation_id)

    def save_conversation(self, state: ConversationState) -> None:
        self._owner(state.owner_id)["conversations"][state.conversation_id] = (
            state.model_dump(mode="json")
        )

    def list_conversations(self, owner_id: str) -> list[dict]:
        conversations = self._owner(owner_id)["conversations"].values()
        return sorted(
            (_conversation_summary(payload) for payload in conversations),
            key=lambda item: item["last_message_at"],
            reverse=True,
        )

    def clear_conversation(self, owner_id: str, conversation_id: str) -> None:
        self._owner(owner_id)["conversations"].pop(conversation_id, None)

    def save_pending(self, action: PendingAction) -> None:
        self._owner(action.owner_id)["pending"][action.conversation_id] = action.model_dump(
            mode="json"
        )

    def get_pending(self, owner_id: str, conversation_id: str) -> PendingAction | None:
        payload = self._owner(owner_id)["pending"].get(conversation_id)
        if not payload:
            return None
        action = PendingAction.model_validate(payload)
        if action.expires_at <= datetime.now(action.expires_at.tzinfo):
            self.clear_pending(owner_id, conversation_id)
            return None
        return action

    def clear_pending(self, owner_id: str, conversation_id: str) -> None:
        self._owner(owner_id)["pending"].pop(conversation_id, None)

    def save_document(self, document: UserDocument) -> None:
        documents = self._owner(document.owner_id)["documents"].setdefault(
            document.conversation_id, {}
        )
        documents[document.document_id] = document.model_dump(mode="json")

    def list_documents(self, owner_id: str, conversation_id: str) -> list[UserDocument]:
        documents = self._owner(owner_id)["documents"].get(conversation_id, {})
        return [UserDocument.model_validate(payload) for payload in documents.values()]

    def delete_document(
        self, owner_id: str, conversation_id: str, document_id: str
    ) -> None:
        documents = self._owner(owner_id)["documents"].get(conversation_id, {})
        documents.pop(document_id, None)

    def clear_documents(self, owner_id: str, conversation_id: str) -> None:
        self._owner(owner_id)["documents"].pop(conversation_id, None)


def _conversation_summary(payload: dict) -> dict:
    state = ConversationState.model_validate(payload)
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
