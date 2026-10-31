from stylemate.agent.citations import cited_sources
from stylemate.domain.models import KnowledgeSource


def test_unrelated_retrieved_sources_do_not_become_answer_citations():
    source = KnowledgeSource(id="known", title="Known", url="https://example.test/care")
    assert cited_sources("未找到税务资料，检索结果与问题无关。", [source]) == []
    assert cited_sources("[引用](https://example.test/invented)", [source]) == []
    assert cited_sources("https://example.test/care-unrelated", [source]) == []


def test_explicit_known_urls_are_deduplicated_and_support_fragments():
    source = KnowledgeSource(id="known", title="Known", url="https://example.test/care?a=1&b=2")
    answer = "按照[护理指南](https://example.test/care?a=1&amp;b=2#drying)处理。"
    assert cited_sources(answer, [source, source]) == [source]
    user_source = source.model_copy(update={"url": "user-document://guide"})
    assert cited_sources("[用户资料](user-document://guide)", [user_source]) == [user_source]
