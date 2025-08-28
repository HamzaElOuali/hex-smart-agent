# app/main.py
# ──────────────────────────────────────────────────────────────────────────────
#  Hex Smart Agent  – FastAPI backend
#  version 0.2.4  (single best source + stricter list formatting)
# ──────────────────────────────────────────────────────────────────────────────
import os, re, json, requests
from typing import List, Optional

from fastapi import (
    FastAPI, Depends, UploadFile, File, Form,
    HTTPException, status, Query
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel, Field

import fitz  # PyMuPDF
import httpx

# ───────────────────────── helpers ───────────────────────────────────────────
def _norm(fname: str) -> str:
    return os.path.basename(fname).strip().lower()

# canonical-filename helper: strips “_1”, “_2”… before .pdf
def _canon(fname: str) -> str:
    """
    Basename → lowercase → trim → strip trailing '_<digits>' added by _safe_filename().
    Example: 'myfile_3.pdf' -> 'myfile.pdf'
    """
    base = os.path.basename(fname or "").strip().lower()
    return re.sub(r"_\d+(?=\.[a-z0-9]+$)", "", base)

# ───────────────────────── local imports ─────────────────────────────────────
from .security  import verify_token
from .          import models
from .database  import engine, Base, get_db
from .embedding import (
    store_chunks_in_weaviate,
    create_weaviate_schema,
    search_chunks,
)

# ───────────────────────── Configuration ─────────────────────────────────────
DATA_DIR       = os.getenv("PDF_DATA_DIR", "./data/pdfs")
VECTOR_ENABLED = os.getenv("VECTOR_ENABLED", "true").lower() == "true"
os.makedirs(DATA_DIR, exist_ok=True)

# ───────────────────────── FastAPI app ───────────────────────────────────────
app = FastAPI(title="Hex Smart Agent Backend", version="0.2.4")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:3000").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ───────────────────────── Startup ───────────────────────────────────────────
@app.on_event("startup")
def _startup() -> None:
    Base.metadata.create_all(bind=engine)
    try:
        create_weaviate_schema()
    except Exception as exc:
        print(f"[Startup] vector-store init failed: {exc}")

# ───────────────────────── Pydantic DTOs ─────────────────────────────────────
class DocumentOut(BaseModel):
    id: int
    title: str
    filename: str
    description: Optional[str] = None
    role: str
    model_config = {"from_attributes": True}

class DocumentContentOut(BaseModel):
    title: str
    content: str

class SearchResult(BaseModel):
    doc_id: int
    title: str
    chunk_index: int
    page_num: Optional[int] = None
    chunk: str
    filename: Optional[str] = None
    score: Optional[float] = None
    distance: Optional[float] = None

class UploadResponse(BaseModel):
    message: str
    doc_id: int
    chunk_count: int
    vector_indexed: bool

# ───────────────────────── Helpers ───────────────────────────────────────────
ALLOWED_EXTENSIONS = {".pdf"}
ALLOWED_MIME       = {"application/pdf"}

def _validate_pdf_upload(file: UploadFile) -> None:
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type '{ext}'. Only PDF is allowed.")
    if file.content_type not in ALLOWED_MIME:
        print(f"[Upload] warning: content-type={file.content_type}")

def _safe_filename(name: str) -> str:
    base        = os.path.basename(name)
    prefix, ext = os.path.splitext(base)
    candidate   = base
    i           = 1
    while os.path.exists(os.path.join(DATA_DIR, candidate)):
        candidate = f"{prefix}_{i}{ext}"
        i += 1
    return candidate

# ───────────────────────── Routes ────────────────────────────────────────────
@app.get("/")
def root():
    return {"message": "Hello from FastAPI backend!", "vector_enabled": VECTOR_ENABLED}

@app.get("/healthz")
def healthz(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception as exc:
        db_ok = False
        print(f"[Health] DB error: {exc}")
    return {"status": "ok" if db_ok else "degraded", "db": db_ok, "vector": VECTOR_ENABLED}

# ───────────────────────── Upload PDF ────────────────────────────────────────
@app.post("/upload-document", response_model=UploadResponse)
async def upload_document(
    file : UploadFile = File(...),
    title: str        = Form(...),
    description: str  = Form(""),
    role : str        = Form("user"),
    db   : Session    = Depends(get_db),
    user              = Depends(verify_token),
):
    if role != "user" and user.get("role", "user") != "admin":
        raise HTTPException(403, "Insufficient privileges to assign this role.")

    _validate_pdf_upload(file)

    # save PDF
    safe_name = _safe_filename(file.filename)
    path      = os.path.join(DATA_DIR, safe_name)
    with open(path, "wb") as fh:
        fh.write(await file.read())

    # extract text
    page_texts, page_nums = [], []
    with fitz.open(path) as pdf:
        for idx, page in enumerate(pdf, start=1):
            txt = page.get_text().strip()
            if txt:
                page_texts.append(txt)
                page_nums.append(idx)

    full_text = "\n".join(page_texts)
    if not full_text:
        raise HTTPException(400, "The PDF appears to contain no extractable text.")

    # persist metadata
    doc = models.Document(
        title=title, filename=safe_name, description=description,
        role=role, content=full_text,
    )
    db.add(doc); db.commit(); db.refresh(doc)

    # vector index
    chunk_count, vect_ok = 0, False
    try:
        chunk_count = store_chunks_in_weaviate(doc, page_texts, page_nums)
        vect_ok     = bool(chunk_count)
    except Exception as exc:
        print(f"[Vector] {exc}")

    return UploadResponse(
        message="Document uploaded successfully.",
        doc_id=doc.id, chunk_count=chunk_count, vector_indexed=vect_ok,
    )

# ───────────────────────── List / fetch docs ────────────────────────────────
@app.get("/documents", response_model=List[DocumentOut])
def list_documents(
    limit : int  = Query(50, ge=1, le=500),
    offset: int  = Query(0, ge=0),
    q     : Optional[str] = Query(None),
    user  = Depends(verify_token),
    db    : Session = Depends(get_db),
):
    role = user.get("role", "user")
    qset = db.query(models.Document).filter(models.Document.role.in_([role, "user"]))
    if q:
        qset = qset.filter(models.Document.title.ilike(f"%{q}%"))
    return (
        qset.order_by(models.Document.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

@app.get("/documents/{doc_id}", response_model=DocumentContentOut)
def get_document_content(doc_id: int, user = Depends(verify_token), db: Session = Depends(get_db)):
    role = user.get("role", "user")
    doc  = db.query(models.Document).filter(models.Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    if doc.role not in (role, "user"):
        raise HTTPException(403, "Forbidden")
    return {"title": doc.title, "content": doc.content}

# ───────────────────────── Vector search ────────────────────────────────────
@app.get("/search", response_model=List[SearchResult])
def search(query: str, limit: int = 5, user = Depends(verify_token)):
    if not VECTOR_ENABLED:
        return []
    role = user.get("role", "user")
    return search_chunks(query=query, role=role, limit=limit)

# ───────────────────────── /ask  (RAG) ───────────────────────────────────────
OPENROUTER_API_KEY  = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL    = os.getenv("OPENROUTER_MODEL", "mistralai/mistral-small-3.1-24b-instruct:free")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1/chat/completions")

class AskRequest(BaseModel):
    question : str
    top_k    : int  = Field(10, ge=1, le=20)
    min_score: float = Field(0.15, ge=0.0, le=1.0)

class SourceChunk(BaseModel):
    doc_id     : int
    title      : str
    page_num   : Optional[int]
    chunk_index: int
    text       : str
    score      : Optional[float] = None
    filename   : Optional[str]   = None

class AskResponse(BaseModel):
    answer : str
    sources: List[SourceChunk]

def _build_router_body(system_prompt: str, user_prompt: str) -> dict:
    return {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        "temperature": 0.0,
        "presence_penalty": 0,
        "frequency_penalty": 0,
        "max_tokens": 800,
    }

def _call_openrouter_sync(body: dict) -> str:
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    r = requests.post(OPENROUTER_BASE_URL, headers=headers, data=json.dumps(body), timeout=60)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()

# keep for other uses (not used for final 1-source emission)
def dedup_sources(items):
    seen, out = set(), []
    for r in items:
        key = (_canon(r.get("filename", "")), r.get("page_num") or "?")
        if key in seen:
            continue
        seen.add(key)
        out.append(
            SourceChunk(
                doc_id      = r["doc_id"],
                title       = r["title"],
                page_num    = r.get("page_num"),
                chunk_index = r["chunk_index"],
                text        = r["chunk"],
                score       = r.get("score"),
                filename    = r.get("filename"),
            )
        )
    return out

# NEW: choose exactly one best supporting chunk by highest score
def pick_best_source(items):
    if not items:
        return None
    best = max(items, key=lambda r: (r.get("score") or 0.0))
    return SourceChunk(
        doc_id      = best["doc_id"],
        title       = best["title"],
        page_num    = best.get("page_num"),
        chunk_index = best["chunk_index"],
        text        = best["chunk"],
        score       = best.get("score"),
        filename    = best.get("filename"),
    )

# ───────────────────────── /ask endpoint ─────────────────────────────────────
@app.post("/ask", response_model=AskResponse, tags=["RAG"])
async def ask(req: AskRequest, stream: bool = False, user = Depends(verify_token)):
    if not OPENROUTER_API_KEY:
        raise HTTPException(500, "OPENROUTER_API_KEY not configured")

    role   = user.get("role", "user")
    hits   = search_chunks(req.question, role, limit=req.top_k)
    ctx    = [h for h in hits if (h.get("score") or 0) >= req.min_score]

    # no useful context
    if not ctx:
        empty = AskResponse(answer="I don’t know based on the provided documents.", sources=[])
        if stream:
            return StreamingResponse(
                (l.encode() for l in ["data: " + empty.model_dump_json() + "\n\n"]),
                media_type="text/event-stream"
            )
        return empty

    # build prompt
    context = "\n\n".join(
        f"[{c['filename']} p{c.get('page_num','?')}] {c['chunk']}" for c in ctx
    )
    system_prompt = (
        "You are Hex-Doc Agent. Prefer answers grounded in CONTEXT; "
        "if you are certain CONTEXT lacks the answer, say so. "
        "Keep replies under 150 words.\n"
        "Format multi-step instructions as a numbered list. Each step MUST be on its own line and start with:\n"
        "1. **Short Title**: action...\n"
        "2. **Short Title**: action...\n"
        
    )
    user_prompt = f"QUESTION:\n{req.question}\n\nCONTEXT:\n{context}\n\nAnswer:"
    body = _build_router_body(system_prompt, user_prompt)


    # ─── JSON branch ─────────────────────────────────────────────────────────
    if not stream:
        try:
            answer = _call_openrouter_sync(body)
        except Exception as exc:
            print("[ASK] LLM error:", exc)
            raise HTTPException(502, "OpenRouter API error")

        one = pick_best_source(ctx)
        return AskResponse(answer=answer, sources=[] if one is None else [one])

    # ─── streaming SSE branch ───────────────────────────────────────────────
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json", "Accept": "text/event-stream"}

    async def event_generator():
        # prime an empty answer frame so UI can open a bubble
        yield "data: " + json.dumps({"answer": ""}) + "\n\n"
        buffer = ""
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("POST", OPENROUTER_BASE_URL,
                                          headers=headers, json=body) as resp:
                    async for chunk in resp.aiter_text():
                        if chunk:
                            buffer += chunk
                            frames = buffer.split("\n\n")
                            buffer = frames.pop()
                            for raw in frames:
                                raw = raw.strip()
                                if not raw:
                                    continue
                                if not raw.startswith("data:"):
                                    raw = "data: " + raw
                                yield raw + "\n\n"
        except Exception as exc:
            print("[ASK] streaming error:", exc)
            yield "event: error\ndata: OpenRouter stream failed\n\n"
            return

        # flush last partial token
        if buffer.strip():
            tail = buffer if buffer.startswith("data:") else "data: " + buffer
            yield tail.rstrip() + "\n\n"

        # ---------- send exactly one best source ----------
        one = pick_best_source(ctx)
        unique = [] if one is None else [one.model_dump()]
        yield "data: " + json.dumps({"sources": unique}) + "\n\n"
        yield "event: done\ndata: end\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# ─────────────────────────────────────────────────────────────────────────────
