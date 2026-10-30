from langchain_core.messages import AIMessage

from stylemate.agent.policy import current_outfits, record_outfits, request_policy
from stylemate.demo.sample_data import sample_garments
from tests.agent.test_service import service


def test_deterministic_knowledge_answer_cites_only_the_displayed_snippet():
    payload = {"result": {"results": [{"snippet": "实际展示的建议", "source_url": "https://example.com/first"},
                                      {"snippet": "没有展示的建议", "source_url": "https://example.com/second"}]},
               "sources": [{"title": "第一条", "url": "https://example.com/first"},
                           {"title": "第二条", "url": "https://example.com/second"}]}
    answer, _, sources = service()._present_named("rag_search", payload)
    assert answer == "实际展示的建议"
    assert [source.url for source in sources] == ["https://example.com/first"]


def test_inventory_result_is_typed_saved_and_does_not_leak_to_next_turn_or_owner():
    app = service()
    for garment in sample_garments():
        app.wardrobe_repository.save_garment("owner-a", garment)
    reply = app.chat("owner-a", "thread-a", "推荐通勤搭配")
    assert reply.outfits
    owned = {garment.id for garment in app.wardrobe_repository.list_garments("owner-a")}
    assert all(set(outfit.garment_ids) <= owned for outfit in reply.outfits)
    saved = app.repository.load_conversation("owner-a", "thread-a")
    assert saved.transcript[-1].outfits == reply.outfits
    assert app.chat("owner-a", "thread-a", "你好").outfits == []
    assert app.chat("owner-b", "thread-a", "推荐通勤搭配").outfits == []


def test_model_prose_cannot_create_structured_inventory_cards():
    class Model:
        def bind_tools(self, _tools):
            return self

        def invoke(self, _messages):
            return AIMessage(content='{"outfits":[{"garment_ids":["invented"]}]}')

    app = service()
    app.model = Model()
    assert app.chat("owner", "thread", "随便聊聊").outfits == []


def test_read_only_presentation_collection_is_bounded_and_checks_identity_and_ownership():
    app = service()
    payload = {"id": "one", "garment_ids": ["other-user-item"], "score": 80,
               "reason": "fixture", "constraint_checks": {}}
    with request_policy("owner", "thread", {"recommend_inventory_outfit"}):
        record_outfits("owner", "thread", {"recommendations": [payload]}, app.wardrobe_repository)
        assert current_outfits("owner", "thread") == []
        assert current_outfits("other", "thread") == []
        garment = sample_garments()[0]
        app.wardrobe_repository.save_garment("owner", garment)
        for number in range(5):
            approved = dict(payload, id=str(number), garment_ids=[garment.id])
            record_outfits("owner", "thread", {"recommendations": [approved]}, app.wardrobe_repository)
        assert len(current_outfits("owner", "thread")) == 3
