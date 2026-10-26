import pytest

from stylemate.rag.portable_vectors import PortableVectorClient


def test_persistent_vectors_survive_reopen_and_filter_before_ranking(tmp_path):
    path = tmp_path / "vectors.sqlite3"
    client = PortableVectorClient(path)
    collection = client.get_or_create_collection("owner-a")
    collection.upsert(ids=["other-thread", "own-thread"], documents=["private", "own"],
                      metadatas=[{"conversation_id": "b"}, {"conversation_id": "a"}],
                      embeddings=[[1, 0], [0, 1]])
    reopened = PortableVectorClient(path).get_collection("owner-a")
    result = reopened.query(query_embeddings=[[1, 0]], n_results=10, where={"conversation_id": "a"})
    assert result["ids"] == [["own-thread"]]
    assert reopened.count() == 2
    with pytest.raises(ValueError, match="collection_not_found"):
        PortableVectorClient(path).get_collection("owner-b")


def test_invalid_dimensions_and_nan_do_not_write_partial_batch():
    collection = PortableVectorClient().get_or_create_collection("safe")
    collection.upsert(ids=["a"], documents=["a"], embeddings=[[1, 0]])
    with pytest.raises(ValueError, match="dimension"):
        collection.upsert(ids=["b"], documents=["b"], embeddings=[[1, 0, 0]])
    with pytest.raises(ValueError, match="invalid_vector"):
        collection.upsert(ids=["c"], documents=["c"], embeddings=[[float("nan"), 0]])
    assert collection.get()["ids"] == ["a"]


def test_delete_scope_and_rank_order_are_deterministic():
    collection = PortableVectorClient().get_or_create_collection("safe")
    collection.upsert(ids=["a", "b"], documents=["a", "b"], embeddings=[[1, 0], [0, 1]],
                      metadatas=[{"conversation_id": "a"}, {"conversation_id": "b"}])
    assert collection.query(query_embeddings=[[1, 0]], n_results=2)["ids"] == [["a", "b"]]
    collection.delete(where={"conversation_id": "b"})
    assert collection.get()["ids"] == ["a"]
