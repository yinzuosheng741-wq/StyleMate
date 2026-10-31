from pathlib import Path

from scripts.build_desktop import copy_user_guides
from scripts.check_docs import broken_links, public_markdown


def test_relative_guide_images_survive_one_more_directory_level(tmp_path):
    guide = tmp_path / "docs/guides/guide.md"
    image = tmp_path / "docs/assets/setup.png"
    guide.parent.mkdir(parents=True)
    image.parent.mkdir(parents=True)
    image.write_bytes(b"test-image")
    guide.write_text("![Setup](../assets/setup.png)\n[External](https://example.org)\n[Section](#setup)", encoding="utf-8")
    assert broken_links(tmp_path, [guide]) == []
    image.unlink()
    assert broken_links(tmp_path, [guide]) == ["docs/guides/guide.md: ../assets/setup.png"]


def test_local_link_check_handles_encoded_spaces_and_ignores_code_examples(tmp_path):
    guide = tmp_path / "README.md"
    (tmp_path / "user guide.md").write_text("guide", encoding="utf-8")
    guide.write_text('[Guide](user%20guide.md)\n[Guide](<user guide.md>)\n```text\n[Example](missing.md)\n```', encoding="utf-8")
    assert broken_links(tmp_path, [guide]) == []
    guide.write_text("[Missing](../outside.md)", encoding="utf-8")
    assert broken_links(tmp_path, [guide]) == ["README.md: ../outside.md"]


def test_public_repository_documentation_has_no_missing_local_targets():
    root = Path(__file__).resolve().parents[1]
    documents = public_markdown(root)
    assert root / "docs/README.md" in documents
    assert all("local" not in p.relative_to(root).parts for p in documents)
    assert broken_links(root, documents) == []


def test_portable_guides_include_both_configuration_images_and_resolve_links(tmp_path):
    copy_user_guides(tmp_path)
    guides = sorted((tmp_path / "docs/guides").glob("*.md"))
    assert {p.name for p in guides} == {"DESKTOP.md", "PORTABLE_20261030.md"}
    assert {p.name for p in (tmp_path / "docs/assets").iterdir()} == {"service-setup.png", "weather-setup.png"}
    assert broken_links(tmp_path, guides) == []
