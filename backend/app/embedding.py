import os, re
from typing import List, Optional
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
import numpy as np

load_dotenv()

VECTOR_ENABLED = os.getenv("VECTOR_ENABLED", "true").lower() == "true"
MODEL_NAME     = os.getenv("EMBED_MODEL", "all-MiniLM-L6-v2")
EMBED_DEBUG    = os.getenv("EMBED_DEBUG", "false").lower() == "true"
model          = SentenceTransformer(MODEL_NAME)

COLLECTION_NAME = "DocumentChunk"

if VECTOR_ENABLED:
    import weaviate
    from weaviate.collections.classes.config import Property, DataType, Configure
    from weaviate.classes.query import Filter

_client = None

# ── connection helpers ────────────────────────────────────────────
def connect_weaviate():
    if not VECTOR_ENABLED:
        return None
    host      = os.getenv("WEAVIATE_HOST", "localhost")
    http_port = int(os.getenv("WEAVIATE_PORT", "8080"))
    grpc_port = int(os.getenv("WEAVIATE_GRPC_PORT", "50051"))
    try:
        return weaviate.connect_to_local(host=host, port=http_port, grpc_port=grpc_port)
    except Exception as e:
        print("[Weaviate] Connection failed:", e)
        return None

def get_client():
    global _client
    if not VECTOR_ENABLED:
        return None
    if _client is None or (hasattr(_client, "is_ready") and not _client.is_ready()):
        _client = connect_weaviate()
    return _client

def close_client():
    global _client
    if _client and not _client.is_closed():
        _client.close(); _client = None

# ── schema ────────────────────────────────────────────────────────
def create_weaviate_schema():
    if not VECTOR_ENABLED:
        return
    client = get_client()
    if client and not client.collections.exists(COLLECTION_NAME):
        client.collections.create(
            name=COLLECTION_NAME,
            properties=[
                Property(name="doc_id",      data_type=DataType.INT),
                Property(name="title",       data_type=DataType.TEXT),
                Property(name="filename",    data_type=DataType.TEXT),
                Property(name="description", data_type=DataType.TEXT),
                Property(name="role",        data_type=DataType.TEXT),
                Property(name="chunk",       data_type=DataType.TEXT),
                Property(name="chunk_index", data_type=DataType.INT),
                Property(name="page_num",    data_type=DataType.INT),      # ← new
            ],
            vectorizer_config=Configure.Vectorizer.none(),
        )

# ── text helpers ──────────────────────────────────────────────────
def split_text(text: str, max_tokens: int = 256) -> List[str]:
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    chunks, cur, tokens = [], [], 0
    for s in sentences:
        w = len(s.split())
        if tokens + w > max_tokens and cur:
            chunks.append(" ".join(cur)); cur, tokens = [], 0
        cur.append(s); tokens += w
    if cur: chunks.append(" ".join(cur))
    return [c.strip() for c in chunks if c.strip()]

def split_text_with_pages(page_texts: List[str], page_nums: List[int], max_tokens=256):
    pieces, pages = [], []
    for txt, pg in zip(page_texts, page_nums):
        cks = split_text(txt, max_tokens)
        pieces.extend(cks); pages.extend([pg]*len(cks))
    return pieces, pages

def embed_texts(texts: List[str]) -> np.ndarray:
    return model.encode(texts, convert_to_numpy=True)

# ── ingestion ─────────────────────────────────────────────────────
def store_chunks_in_weaviate(doc, page_texts: List[str], page_nums: List[int]) -> Optional[int]:
    if not VECTOR_ENABLED:
        return None
    client = get_client()
    if client is None:
        return None

    chunks, pages = split_text_with_pages(page_texts, page_nums)
    if not chunks: return 0

    vectors = embed_texts(chunks)
    col     = client.collections.get(COLLECTION_NAME)
    with col.batch.dynamic() as batch:
        for i, chunk in enumerate(chunks):
            batch.add_object(
                properties=dict(
                    doc_id=doc.id, title=doc.title, filename=doc.filename,
                    description=doc.description, role=doc.role,
                    chunk_index=i, page_num=pages[i], chunk=chunk
                ),
                vector=vectors[i],
            )
    return len(chunks)

# ── semantic search ───────────────────────────────────────────────
def search_chunks(query: str, role: str, limit: int = 5):
    if not VECTOR_ENABLED:
        return []
    client = get_client()
    if client is None:
        return []

    vec = model.encode([query], convert_to_numpy=True)[0]
    role_filter = Filter.by_property("role").equal(role) | Filter.by_property("role").equal("user")
    res = client.collections.get(COLLECTION_NAME).query.near_vector(
        near_vector=vec, limit=limit, filters=role_filter,
        return_properties=["doc_id","title","chunk","chunk_index","filename","role","page_num"],
        return_metadata=["distance"]
    )
    out = []
    for o in res.objects:
        p, d = o.properties, o.metadata.distance
        out.append({
            "doc_id": p.get("doc_id"), "title": p.get("title"),
            "chunk_index": p.get("chunk_index"), "page_num": p.get("page_num"),
            "chunk": p.get("chunk"), "filename": p.get("filename"),
            "role": p.get("role"), "distance": d, "score": 1-d if d is not None else None,
        })
    return out
