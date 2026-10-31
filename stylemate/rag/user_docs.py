"""Safe offline extraction for user-supplied reference documents."""

import hashlib
import re
from dataclasses import dataclass
from io import BytesIO

from pypdf import PdfReader

from stylemate.domain.models import UserDocument
from stylemate.rag.models import UserDocumentChunk, UserDocumentText


@dataclass(frozen=True)
class DocumentLimits:
    max_bytes: int = 4 * 1024 * 1024
    max_chars: int = 200_000


class DocumentLimitError(ValueError):
    pass


_TEXT_TYPES = {"text/plain", "text/markdown", "text/x-markdown"}


@dataclass(frozen=True)
class _Section:
    title: str | None
    body: str


def extract_user_document(filename: str, mime_type: str, payload: bytes, limits: DocumentLimits) -> UserDocumentText:
    if len(payload) > limits.max_bytes:
        raise DocumentLimitError(f"\u6587\u4ef6\u4e0d\u80fd\u8d85\u8fc7 {limits.max_bytes // (1024 * 1024)} MB")
    if mime_type in _TEXT_TYPES:
        try:
            text = payload.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("\u6587\u672c\u5fc5\u987b\u4f7f\u7528 UTF-8 \u7f16\u7801") from exc
        pages = [text]
    elif mime_type == "application/pdf":
        try:
            reader = PdfReader(BytesIO(payload))
            if reader.is_encrypted:
                raise ValueError("\u4e0d\u652f\u6301\u52a0\u5bc6 PDF")
            pages = [(page.extract_text() or "").strip() for page in reader.pages]
            text = "\n".join(page for page in pages if page)
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("\u65e0\u6cd5\u8bfb\u53d6 PDF") from exc
    else:
        raise ValueError("\u4e0d\u652f\u6301\u7684\u6587\u6863\u7c7b\u578b\uff0c\u4ec5\u652f\u6301 TXT\u3001MD \u548c PDF")
    if len(text) > limits.max_chars:
        raise DocumentLimitError(f"\u63d0\u53d6\u6587\u672c\u4e0d\u80fd\u8d85\u8fc7 {limits.max_chars} \u4e2a\u5b57\u7b26")
    if not text.strip():
        raise ValueError("文档中没有可检索文本")
    return UserDocumentText(filename=filename, mime_type=mime_type, text=text, pages=pages)


def chunk_user_document(
    document: UserDocument,
    *,
    chunk_size: int = 600,
    overlap: int = 80,
) -> list[UserDocumentChunk]:
    """Create stable, page-aware chunks for lexical and vector retrieval."""
    if chunk_size < 100 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("文档分块参数无效")
    page_texts = document.pages or [document.text]
    grouped_chunks: list[tuple[UserDocumentChunk, tuple[int, int]]] = []
    seen: set[str] = set()
    for page_index, page_text in enumerate(page_texts, start=1):
        sections = _split_sections(page_text)
        for section_index, section in enumerate(sections):
            for text in _split_text(section.body, chunk_size, overlap):
                rendered = f"{section.title}\n{text}" if section.title else text
                content_hash = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
                if content_hash in seen:
                    continue
                seen.add(content_hash)
                source_index = len(grouped_chunks)
                identity = (
                    f"{document.document_id}:{page_index}:{section_index}:"
                    f"{source_index}:{content_hash}"
                )
                grouped_chunks.append(
                    (
                        UserDocumentChunk(
                            chunk_id=hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24],
                            document_id=document.document_id,
                            filename=document.filename,
                            text=rendered,
                            chunk_index=source_index,
                            page_number=page_index
                            if document.mime_type == "application/pdf"
                            else None,
                            section_title=section.title,
                        ),
                        (page_index, section_index),
                    )
                )
    chunks: list[UserDocumentChunk] = []
    for index, (chunk, group) in enumerate(grouped_chunks):
        previous_id = None
        next_id = None
        if index > 0 and grouped_chunks[index - 1][1] == group:
            previous_id = grouped_chunks[index - 1][0].chunk_id
        if index + 1 < len(grouped_chunks) and grouped_chunks[index + 1][1] == group:
            next_id = grouped_chunks[index + 1][0].chunk_id
        chunks.append(
            chunk.model_copy(
                update={
                    "previous_chunk_id": previous_id,
                    "next_chunk_id": next_id,
                }
            )
        )
    return chunks


def _split_sections(text: str) -> list[_Section]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []
    sections: list[_Section] = []
    title: str | None = None
    body_blocks: list[str] = []

    def flush() -> None:
        body = "\n".join(body_blocks).strip()
        if body:
            sections.append(_Section(title=title, body=body))
        body_blocks.clear()

    lines = normalized.splitlines()
    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        standalone = (index == 0 or not lines[index - 1].strip()) and (
            index + 1 == len(lines) or not lines[index + 1].strip()
        )
        heading = _heading_text(line, standalone)
        if heading:
            flush()
            title = heading
        else:
            body_blocks.append(line)
    flush()
    if sections:
        return sections
    return [_Section(title=None, body=normalized)]


def _heading_text(line: str, standalone: bool) -> str | None:
    markdown = re.match(r"^#{1,6}\s+(.+?)\s*#*$", line)
    if markdown:
        return markdown.group(1).strip()[:120]
    if not standalone or len(line) > 60:
        return None
    if re.match(r"^(?:第[一二三四五六七八九十百0-9]+[章节部分]|[一二三四五六七八九十0-9]+[、.．])", line):
        return line[:120]
    if line.endswith(("：", ":")):
        return line.rstrip("：:").strip()[:120]
    return None


def _split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(len(normalized), start + chunk_size)
        if end < len(normalized):
            search_start = start + chunk_size // 2
            boundary = max(
                normalized.rfind(marker, search_start, end)
                for marker in ("\n", "。", "！", "？", ". ")
            )
            if boundary >= search_start:
                end = boundary + 1
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(normalized):
            break
        start = max(start + 1, end - overlap)
    return chunks


__all__ = [
    "DocumentLimitError",
    "DocumentLimits",
    "chunk_user_document",
    "extract_user_document",
]
