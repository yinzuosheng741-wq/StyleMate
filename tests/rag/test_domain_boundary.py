import pytest

from tests.agent.test_service import service


@pytest.mark.parametrize("query", ["帮我预测下周股票价格", "汽车变速箱漏油怎么维修", "服务器数据库备份怎么做", "抗生素药物剂量如何选择"])
def test_explicit_other_domains_do_not_receive_builtin_clothing_evidence(query):
    app = service()
    assert app.retriever.search(query, "owner", "thread") == []
    assert app.retriever.last_audit["vector_candidates"] == 0


@pytest.mark.parametrize("query", ["开车去面试衣服怎么选", "汽车旅行途中衣物怎样分层", "面试衣服和电脑包怎么选"])
def test_clothing_questions_are_not_blocked_just_for_mentioning_another_domain(query):
    assert service().retriever.search(query, "owner", "thread")


def test_uploaded_document_remains_queryable_in_its_own_conversation():
    app = service()
    app.ingest_document("owner", "thread", "notes.txt", "text/plain",
                        "服务器数据库备份采用每日快照，并保留最近七天的备份记录。".encode())
    hits = app.retriever.search("服务器数据库备份", "owner", "thread")
    assert hits and all(hit.document_id for hit in hits)
    assert app.retriever.search("服务器数据库备份", "other-owner", "thread") == []
    assert app.retriever.search("服务器数据库备份", "owner", "other-thread") == []
