"""Per-agent knowledge embeddings.

- Model: OpenAI text-embedding-3-small (settings.EMBED_MODEL / EMBED_DIM)
- Chunking: settings.EMBED_CHUNK_SIZE chars with EMBED_CHUNK_OVERLAP overlap
- Storage: pgvector on Postgres (vector column + cosine index), JSON-in-SQLite
  fallback with pure-python cosine so dev works with zero extra services.
- Every embedding call is recorded in ApiUsage for the super-admin page.
"""
import json
import math
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session
from ..config import settings
from ..database import engine
from .. import models
from . import keys as keysvc

_IS_PG = str(engine.url).startswith(("postgresql", "postgres"))
_PGVECTOR_READY = False


def ensure_pgvector():
    """On Postgres: CREATE EXTENSION vector + a vector column on kb_chunks."""
    global _PGVECTOR_READY
    if not _IS_PG or _PGVECTOR_READY:
        return
    try:
        with engine.begin() as conn:
            conn.execute(sql_text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.execute(sql_text(
                f"ALTER TABLE kb_chunks ADD COLUMN IF NOT EXISTS "
                f"embedding_vec vector({settings.EMBED_DIM})"))
            conn.execute(sql_text(
                "CREATE INDEX IF NOT EXISTS kb_chunks_vec_idx ON kb_chunks "
                "USING hnsw (embedding_vec vector_cosine_ops)"))
        _PGVECTOR_READY = True
    except Exception:
        _PGVECTOR_READY = False


def chunk_text(txt: str) -> list[str]:
    size = settings.EMBED_CHUNK_SIZE
    overlap = settings.EMBED_CHUNK_OVERLAP
    txt = " ".join(txt.split())
    if not txt:
        return []
    chunks, i = [], 0
    while i < len(txt):
        chunks.append(txt[i:i + size])
        i += max(1, size - overlap)
    return chunks[:200]


def _embed(db: Session, texts: list[str], agent_id=None) -> list[list[float]]:
    from openai import OpenAI
    client = OpenAI(api_key=keysvc.openai_key(db))
    resp = client.embeddings.create(model=settings.EMBED_MODEL, input=texts)
    keysvc.record(db, "openai", "embedding", settings.EMBED_MODEL,
                  agent_id=agent_id,
                  input_tokens=getattr(resp.usage, "prompt_tokens", 0) or
                               getattr(resp.usage, "total_tokens", 0))
    return [d.embedding for d in resp.data]


def index_doc(db: Session, doc: models.KnowledgeDoc):
    """Chunk + embed one knowledge doc (text already extracted)."""
    db.query(models.KbChunk).filter(models.KbChunk.doc_id == doc.id).delete()
    chunks = chunk_text(f"{doc.title}. {doc.content}")
    if not chunks:
        db.commit()
        return 0
    try:
        vectors = _embed(db, chunks, agent_id=doc.agent_id)
    except Exception:
        vectors = [[] for _ in chunks]     # store raw chunks; keyword fallback
    ensure_pgvector()
    for content, vec in zip(chunks, vectors):
        row = models.KbChunk(doc_id=doc.id, agent_id=doc.agent_id,
                             content=content, embedding=json.dumps(vec))
        db.add(row)
        db.flush()
        if _PGVECTOR_READY and vec:
            db.execute(sql_text(
                "UPDATE kb_chunks SET embedding_vec = (:v)::vector WHERE id = :i"),
                {"v": json.dumps(vec), "i": row.id})
    db.commit()
    return len(chunks)


def _cos(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return -1.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1e-9
    nb = math.sqrt(sum(y * y for y in b)) or 1e-9
    return dot / (na * nb)


def search(db: Session, agent_id: int, query: str, k: int = 4) -> list[str]:
    """Top-k KB chunks for this agent (own docs + shared)."""
    try:
        qvec = _embed(db, [query], agent_id=agent_id)[0]
    except Exception:
        qvec = []
    if _IS_PG and _PGVECTOR_READY and qvec:
        rows = db.execute(sql_text(
            "SELECT content FROM kb_chunks WHERE (agent_id = :a OR agent_id IS NULL) "
            "AND embedding_vec IS NOT NULL "
            "ORDER BY embedding_vec <=> (:q)::vector LIMIT :k"),
            {"a": agent_id, "q": json.dumps(qvec), "k": k}).fetchall()
        if rows:
            return [r[0] for r in rows]
    chunks = (db.query(models.KbChunk)
              .filter((models.KbChunk.agent_id == agent_id) |
                      (models.KbChunk.agent_id.is_(None))).all())
    if not chunks:
        return []
    if qvec:
        scored = [( _cos(qvec, json.loads(c.embedding or "[]")), c.content) for c in chunks]
        scored.sort(reverse=True, key=lambda t: t[0])
        return [c for s, c in scored[:k] if s > 0]
    q_words = set(query.lower().split())              # keyword fallback
    scored = [(len(q_words & set(c.content.lower().split())), c.content) for c in chunks]
    scored.sort(reverse=True, key=lambda t: t[0])
    return [c for s, c in scored[:k] if s > 0]
