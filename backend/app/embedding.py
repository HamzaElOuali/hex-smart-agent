# app/embedding.py
# ──────────────────────────────────────────────────────────────────────────────
import os, re
from typing import List, Optional
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
import numpy as np

load_dotenv()

# ─── Config ───────────────────────────────────────────────────────────────────
VECTOR_ENABLED   = os.getenv("VECTOR_ENABLED", "true").lower() == "true"
MODEL_NAME       = os.getenv("EMBED_MODEL", "all-MiniLM-L6-v2")
EMBED_DEBUG      = os.getenv("EMBED_DEBUG", "false").lower() == "true"
DEFAULT_CHUNKTOK = 150
HYBRID_ALPHA     = 0.7

model           = SentenceTransformer(MODEL_NAME)
EMBED_DIM       = model.get_sentence_embedding_dimension()
COLLECTION_NAME = "DocumentChunk"

if VECTOR_ENABLED:
    import weaviate
    from weaviate.collections.classes.config import Property, DataType, Configure
    from weaviate.classes.query import Filter

_client = None

# ─── Weaviate connection helpers ─────────────────────────────────────────────
def connect_weaviate():
    if not VECTOR_ENABLED:
        return None
    host      = os.getenv("WEAVIATE_HOST", "localhost")
    http_port = int(os.getenv("WEAVIATE_PORT", "8080"))
    grpc_port = int(os.getenv("WEAVIATE_GRPC_PORT", "50051"))
    return weaviate.connect_to_local(host=host, port=http_port, grpc_port=grpc_port)

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

# ─── Schema ──────────────────────────────────────────────────────────────────
def create_weaviate_schema():
    """
    Create the collection if missing; otherwise ensure required properties exist.
    This prevents older data (without page_num, etc.) from breaking UI references.
    """
    if not VECTOR_ENABLED:
        return
    client = get_client()
    if client is None:
        return

    required_props = [
        ("doc_id",      DataType.INT),
        ("title",       DataType.TEXT),
        ("filename",    DataType.TEXT),
        ("description", DataType.TEXT),
        ("role",        DataType.TEXT),
        ("chunk",       DataType.TEXT),
        ("chunk_index", DataType.INT),
        ("page_num",    DataType.INT),
    ]

    if not client.collections.exists(COLLECTION_NAME):
        client.collections.create(
            name=COLLECTION_NAME,
            properties=[Property(name, dtype) for name, dtype in required_props],
            vectorizer_config=Configure.Vectorizer.none(),
            vector_index_config=Configure.VectorIndex.hnsw(dimensions=EMBED_DIM),
        )
        if EMBED_DEBUG:
            print(f"[Weaviate] created {COLLECTION_NAME} (dim={EMBED_DIM})")
        return

    # Self-heal: add any missing properties
    col = client.collections.get(COLLECTION_NAME)
    try:
        cfg = col.config.get()
        existing = {p.name for p in cfg.properties}
    except Exception as e:
        if EMBED_DEBUG:
            print("[Weaviate] config.get() failed; skipping property sync:", e)
        return

    for pname, ptype in required_props:
        if pname not in existing:
            try:
                col.config.add_property(Property(pname, ptype))
                if EMBED_DEBUG:
                    print(f"[Weaviate] added missing property: {pname}")
            except Exception as e:
                print(f"[Weaviate] failed to add property {pname}: {e}")

# ─── Text helpers ────────────────────────────────────────────────────────────
def split_text(text: str, max_tokens: int = DEFAULT_CHUNKTOK) -> List[str]:
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    chunks, cur, tok = [], [], 0
    for s in sentences:
        w = len(s.split())
        if tok + w > max_tokens and cur:
            chunks.append(" ".join(cur)); cur, tok = [], 0
        cur.append(s); tok += w
    if cur: chunks.append(" ".join(cur))
    return [c.strip() for c in chunks if c.strip()]

def split_text_with_pages(page_texts: List[str], page_nums: List[int]) -> tuple[List[str], List[int]]:
    pieces, pages = [], []
    for txt, pg in zip(page_texts, page_nums):
        cks = split_text(txt)
        pieces.extend(cks); pages.extend([pg]*len(cks))
    return pieces, pages

def embed_texts(texts: List[str]) -> np.ndarray:
    return model.encode(texts, convert_to_numpy=True)

# ─── Ingestion ───────────────────────────────────────────────────────────────
def store_chunks_in_weaviate(doc, page_texts: List[str], page_nums: List[int]) -> Optional[int]:
    if not VECTOR_ENABLED:
        return None
    client = get_client()
    if client is None:
        return None

    chunks, pages = split_text_with_pages(page_texts, page_nums)
    if not chunks:
        return 0

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

    print(f"[Weaviate] Stored {len(chunks)} chunks for doc_id={doc.id}")
            
    if EMBED_DEBUG:
        print(f"[Weaviate] stored {len(chunks)} chunks for doc {doc.id}")
    return len(chunks)

# ─── Maintenance (used by /admin/reindex/{doc_id}) ───────────────────────────
def delete_doc_chunks(doc_id: int) -> int:
    """
    Delete all vector objects for a given doc_id.
    Returns number of matches deleted (if available).
    """
    if not VECTOR_ENABLED:
        return 0
    client = get_client()
    if client is None:
        return 0
    col = client.collections.get(COLLECTION_NAME)
    try:
        res = col.data.delete_many(where=Filter.by_property("doc_id").equal(doc_id))
        return getattr(res, "matches", 0)
    except Exception as e:
        print(f"[Weaviate] delete_many failed for doc_id={doc_id}: {e}")
        return 0

# ─── Hybrid search (vector + BM25) ───────────────────────────────────────────
def search_chunks(query: str, role: str, limit: int = 8, alpha: float = HYBRID_ALPHA):
    if not VECTOR_ENABLED:
        return []
    client = get_client()
    if client is None:
        return []

    # Embed the query (vectorizer disabled at collection level)
    vec = model.encode([query], convert_to_numpy=True)[0].tolist()

    role_filter = (
        Filter.by_property("role").equal(role)
        | Filter.by_property("role").equal("user")
    )

    col = client.collections.get(COLLECTION_NAME)
    res = col.query.hybrid(
        query=query,                 # BM25 part
        vector=vec,                  # vector part
        alpha=alpha,
        limit=limit,
        filters=role_filter,
        return_properties=[
            "doc_id", "title", "chunk", "chunk_index",
            "filename", "role", "page_num"
        ],
        return_metadata=["score", "distance"],
    )

    out = []
    for obj in res.objects:
        p, m = obj.properties, obj.metadata
        out.append({
            "doc_id":      p.get("doc_id"),
            "title":       p.get("title"),
            "chunk_index": p.get("chunk_index"),
            "page_num":    p.get("page_num"),
            "chunk":       p.get("chunk"),
            "filename":    p.get("filename"),
            "role":        p.get("role"),
            "distance":    getattr(m, "distance", None),
            "score":       getattr(m, "score", None),
        })
    return out
