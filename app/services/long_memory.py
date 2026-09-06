"""Долгая память: ChromaDB + эмбеддинги OpenAI + загрузка документов."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List

import chromadb
from chromadb.utils import embedding_functions

from app import config

logger = logging.getLogger(__name__)

SHARED_KB_COLLECTION = "salon_knowledge_base"

_client: chromadb.PersistentClient | None = None
_ef = None


def _get_client() -> chromadb.PersistentClient:
    global _client, _ef
    if _client is None:
        Path(config.MEMORY_DIR).mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(config.MEMORY_DIR))
        # Используем локальные эмбеддинги ChromaDB, так как Google прокси не поддерживает /embeddings
        _ef = embedding_functions.DefaultEmbeddingFunction()
    return _client


def _embedding_function():
    _get_client()
    return _ef


def collection_name(user_id: int) -> str:
    return f"user_{user_id}"


def get_user_collection(user_id: int):
    return _get_client().get_or_create_collection(
        name=collection_name(user_id),
        embedding_function=_embedding_function(),
        metadata={"hnsw:space": "cosine"},
    )


def get_shared_kb_collection():
    return _get_client().get_or_create_collection(
        name=SHARED_KB_COLLECTION,
        embedding_function=_embedding_function(),
        metadata={"hnsw:space": "cosine"},
    )


def load_document(file_path: str | Path) -> str:
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".txt":
        return path.read_text(encoding="utf-8", errors="ignore")

    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        parts = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(p for p in parts if p.strip())

    if suffix in {".docx", ".doc"}:
        from docx import Document

        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())

    raise ValueError(f"Неподдерживаемый формат: {suffix}")


def split_into_chunks(
    text: str,
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> List[str]:
    chunk_size = chunk_size or config.CHUNK_SIZE
    overlap = overlap or config.CHUNK_OVERLAP
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []

    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(0, end - overlap)
    return chunks


def embed_chunks(user_id: int, chunks: List[str], source_name: str) -> int:
    if not chunks:
        return 0
    collection = get_user_collection(user_id)
    existing = collection.get()
    if existing and existing["ids"]:
        collection.delete(ids=existing["ids"])
    ids = [f"{source_name}_{i}" for i in range(len(chunks))]
    metadatas = [{"source": source_name, "chunk_index": i} for i in range(len(chunks))]
    collection.add(documents=chunks, ids=ids, metadatas=metadatas)
    return len(chunks)


def clear_user_docs(user_id: int) -> None:
    collection = get_user_collection(user_id)
    existing = collection.get()
    if existing and existing["ids"]:
        collection.delete(ids=existing["ids"])


def retrieve_user_context(user_id: int, query: str, top_k: int | None = None) -> str:
    top_k = top_k or config.TOP_K
    collection = get_user_collection(user_id)
    if collection.count() == 0:
        return ""
    results = collection.query(
        query_texts=[query], n_results=min(top_k, collection.count())
    )
    documents = (results.get("documents") or [[]])[0]
    if not documents:
        return ""
    return "\n\n".join(f"[{i + 1}] {doc}" for i, doc in enumerate(documents) if doc)


def seed_shared_knowledge_base() -> int:
    path = Path(config.KNOWLEDGE_FILE)
    if not path.exists():
        logger.warning("Файл базы знаний не найден: %s", path)
        return 0

    chunks = split_into_chunks(path.read_text(encoding="utf-8"))
    if not chunks:
        return 0

    collection = get_shared_kb_collection()
    existing = collection.get()
    if existing and existing["ids"]:
        collection.delete(ids=existing["ids"])

    ids = [f"kb_{i}" for i in range(len(chunks))]
    metadatas = [{"source": path.name, "chunk_index": i} for i in range(len(chunks))]
    collection.add(documents=chunks, ids=ids, metadatas=metadatas)
    logger.info("База знаний проиндексирована: %s чанков", len(chunks))
    return len(chunks)


def retrieve_shared_kb(query: str, top_k: int | None = None) -> str:
    top_k = top_k or config.TOP_K
    collection = get_shared_kb_collection()
    if collection.count() == 0:
        return ""
    results = collection.query(
        query_texts=[query], n_results=min(top_k, collection.count())
    )
    documents = (results.get("documents") or [[]])[0]
    if not documents:
        return ""
    return "\n\n".join(
        f"[БЗ {i + 1}] {doc}" for i, doc in enumerate(documents) if doc
    )


def retrieve_all_context(user_id: int, query: str) -> str:
    parts: list[str] = []
    shared = retrieve_shared_kb(query)
    if shared:
        parts.append("=== База знаний салона ===\n" + shared)
    personal = retrieve_user_context(user_id, query)
    if personal:
        parts.append("=== Документы пользователя ===\n" + personal)
    return "\n\n".join(parts)
