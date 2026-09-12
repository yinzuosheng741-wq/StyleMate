from types import SimpleNamespace

from stylemate.diagnostics import runtime_diagnostics


def test_runtime_diagnostics_is_redacted(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-secret-value")
    settings = SimpleNamespace(app_mode="demo", text_model_name="demo", embedding_model_name="embed")
    retriever = SimpleNamespace(stats=lambda: {"search_requests": 2})

    result = runtime_diagnostics(settings, retriever)

    assert result["text_model_configured"] is True
    assert result["rag_mode"] == "hybrid"
    assert result["retriever_stats"] == {"search_requests": 2}
    assert "sk-secret" not in str(result)
