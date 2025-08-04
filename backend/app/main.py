# app/main.py
# ──────────────────────────────────────────────────────────────────────────────
#  Hex Smart Agent  – FastAPI backend
# ──────────────────────────────────────────────────────────────────────────────
import os, json, requests
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

from .security  import verify_token
from .          import models
from .database  import engine, Base, get_db
from .embedding import (
    store_chunks_in_weaviate,
    create_weaviate_schema,
    search_chunks,
)

# ───────────────────────── Configuration ──────────────────────────
DATA_DIR       = os.getenv("PDF_DATA_DIR", "./data/pdfs")
VECTOR_ENABLED = os.getenv("VECTOR_ENABLED", "true").lower() == "true"
os.makedirs(DATA_DIR, exist_ok=True)

# ───────────────────────── FastAPI app ────────────────────────────
app = FastAPI(title="Hex Smart Agent Backend", version="0.2.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:3000").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ───────────────────────── Startup ────────────────────────────────
@app.on_event("startup")
def _startup() -> None:
    Base.metadata.create_all(bind=engine)
    try:
        create_weaviate_schema()
    except Exception as exc:
        print(f"[Startup] vector-store init failed: {exc}")

# ───────────────────────── Pydantic models ────────────────────────
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

# ───────────────────────── Helpers ────────────────────────────────
ALLOWED_EXTENSIONS = {".pdf"}
ALLOWED_MIME       = {"application/pdf"}

def _validate_pdf_upload(file: UploadFile) -> None:
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type '{ext}'. Only PDF is allowed.")
    if file.content_type not in ALLOWED_MIME:
        print(f"[Upload] warning: content-type={file.content_type}")

def _safe_filename(name: str) -> str:
    base            = os.path.basename(name)
    prefix, ext     = os.path.splitext(base)
    candidate, i    = base, 1
    while os.path.exists(os.path.join(DATA_DIR, candidate)):
        candidate = f"{prefix}_{i}{ext}"
        i += 1
    return candidate

# ───────────────────────── Routes ─────────────────────────────────
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

# ───────────────────────── Upload PDF ─────────────────────────────
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

    # ── save PDF ────────────────────────────────────────────────
    safe_name  = _safe_filename(file.filename)
    path       = os.path.join(DATA_DIR, safe_name)
    with open(path, "wb") as fh:
        fh.write(await file.read())

    # ── extract text & pages ────────────────────────────────────
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

    # ── persist metadata ───────────────────────────────────────
    doc = models.Document(
        title=title,
        filename=safe_name,
        description=description,
        role=role,
        content=full_text,
    )
    db.add(doc); db.commit(); db.refresh(doc)

    # ── vector index ───────────────────────────────────────────
    chunk_count, vect_ok = 0, False
    try:
        chunk_count = store_chunks_in_weaviate(doc, page_texts, page_nums)
        vect_ok     = bool(chunk_count)
    except Exception as exc:
        print(f"[Vector] {exc}")

    return UploadResponse(
        message        = "Document uploaded successfully.",
        doc_id         = doc.id,
        chunk_count    = chunk_count,
        vector_indexed = vect_ok,
    )

# ───────────────────────── List / fetch docs ─────────────────────
@app.get("/documents", response_model=List[DocumentOut])
def list_documents(
    limit : int  = Query(50, ge=1, le=500),
    offset: int  = Query(0, ge=0),
    q     : Optional[str] = Query(None),
    user             = Depends(verify_token),
    db   : Session    = Depends(get_db),
):
    role = user.get("role", "user")
    qset = db.query(models.Document).filter(models.Document.role.in_([role, "user"]))
    if q:
        qset = qset.filter(models.Document.title.ilike(f"%{q}%"))
    return qset.order_by(models.Document.id.desc()).offset(offset).limit(limit).all()

@app.get("/documents/{doc_id}", response_model=DocumentContentOut)
def get_document_content(doc_id: int, user = Depends(verify_token), db: Session = Depends(get_db)):
    role = user.get("role", "user")
    doc  = db.query(models.Document).filter(models.Document.id == doc_id).first()
    if not doc:              raise HTTPException(404, "Document not found")
    if doc.role not in (role, "user"): raise HTTPException(403, "Forbidden")
    return {"title": doc.title, "content": doc.content}

# ───────────────────────── Vector search ────────────────────────
@app.get("/search", response_model=List[SearchResult])
def search(query: str, limit: int = 5, user = Depends(verify_token)):
    if not VECTOR_ENABLED:
        return []
    role = user.get("role", "user")
    return search_chunks(query=query, role=role, limit=limit)

# ───────────────────────── /ask  (RAG) ───────────────────────────
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

# ------------- streaming + non-streaming endpoint -------------
@app.post("/ask", response_model=AskResponse, tags=["RAG"])
async def ask(req: AskRequest, stream: bool = False, user = Depends(verify_token)):
    if not OPENROUTER_API_KEY:
        raise HTTPException(500, "OPENROUTER_API_KEY not configured")

    role      = user.get("role", "user")
    retrieved = search_chunks(req.question, role, limit=req.top_k)
    ctx_items = [r for r in retrieved if (r.get("score") or 0) >= req.min_score]

    if not ctx_items:
        empty = AskResponse(answer="I don’t know based on the provided documents.", sources=[])
        return StreamingResponse(
            (line.encode() for line in ["data: " + empty.model_dump_json() + "\n\n"]),
            media_type="text/event-stream"
        ) if stream else empty

    context = "\n\n".join(
        f"[Doc {r['doc_id']} p{r.get('page_num','?')}] {r['chunk']}"
        for r in ctx_items
    )

    system_prompt = (
        "You are Hex-Doc Agent. Prefer answers grounded in CONTEXT; "
        "if you are certain CONTEXT lacks the answer, say so. "
        "Keep replies under 150 words."
    )
    user_prompt = f"QUESTION:\n{req.question}\n\nCONTEXT:\n{context}\n\nAnswer:"
    body        = _build_router_body(system_prompt, user_prompt)

    # ---------- simple JSON branch ----------
    if not stream:
        try:
            answer = _call_openrouter_sync(body)
        except Exception as exc:
            print("[ASK] LLM error:", exc)
            raise HTTPException(502, "OpenRouter API error")

        sources = [
            SourceChunk(
                doc_id=r["doc_id"], title=r["title"], page_num=r.get("page_num"),
                chunk_index=r["chunk_index"], text=r["chunk"], score=r.get("score"),
                filename=r.get("filename"),
            ) for r in ctx_items
        ]
        return AskResponse(answer=answer, sources=sources)

    # ---------- streaming SSE branch ----------
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}

    async def event_generator():
        # empty shell so the frontend creates the bubble
        yield "data: " + json.dumps({"answer": ""}) + "\n\n"

        buffer = ""  # holds a partial frame

        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("POST", OPENROUTER_BASE_URL, headers=headers, json=body) as resp:
                    async for piece in resp.aiter_text():
                        if not piece:
                            continue
                        buffer += piece

                        # split into complete frames
                        frames = buffer.split("\n\n")
                        buffer = frames.pop()  # leftover partial

                        for raw in frames:
                            line = raw.strip()
                            if not line:
                                continue
                            if not line.startswith("data:"):
                                line = "data: " + line
                            yield line + "\n\n"
        except Exception as exc:
            print("[ASK] streaming error:", exc)
            yield "event: error\ndata: OpenRouter stream failed\n\n"
            return

        # flush final partial frame if any
        if buffer.strip():
            out = buffer if buffer.startswith("data:") else "data: " + buffer
            yield out.rstrip() + "\n\n"

        # deduplicate sources
        unique = {}
        for r in ctx_items:
            key = (r["doc_id"], r.get("page_num"))
            if key not in unique:
                unique[key] = SourceChunk(
                    doc_id=r["doc_id"], title=r["title"], page_num=r.get("page_num"),
                    chunk_index=r["chunk_index"], text=r["chunk"], score=r.get("score"),
                    filename=r.get("filename"),
                )

        yield "data: " + json.dumps({"sources": [s.model_dump() for s in unique.values()]}) + "\n\n"
        yield "event: done\ndata: end\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
# ──────────────────────────────────────────────────────────────────────────────
