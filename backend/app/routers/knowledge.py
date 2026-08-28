"""PER-AGENT knowledge base: every doc belongs to one agent (or is shared).
Supports pasted text and .txt/.md/.pdf/.docx uploads (plain text extraction,
NO OCR — a text layer must exist). Docs are chunked + embedded for retrieval."""
import io
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models, schemas
from ..services import embeddings

router = APIRouter(prefix="/api", tags=["knowledge"])
MAX_DOC = 10 * 1024 * 1024


def _extract_text(filename: str, raw: bytes) -> str:
    name = filename.lower()
    if name.endswith((".txt", ".md")):
        return raw.decode("utf-8", errors="replace")
    if name.endswith(".pdf"):
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(raw))
            return "\n".join((p.extract_text() or "") for p in reader.pages)
        except Exception as e:
            raise HTTPException(400, f"Could not read PDF text: {e}")
    if name.endswith(".docx"):
        try:
            import docx
            d = docx.Document(io.BytesIO(raw))
            return "\n".join(p.text for p in d.paragraphs)
        except Exception as e:
            raise HTTPException(400, f"Could not read DOCX text: {e}")
    raise HTTPException(400, "Only .txt, .md, .pdf or .docx files are supported")


@router.get("/knowledge", response_model=list[schemas.KnowledgeOut])
def list_docs(agent_id: int | None = Query(default=None),
              db: Session = Depends(get_db)):
    q = db.query(models.KnowledgeDoc)
    if agent_id is not None:
        q = q.filter((models.KnowledgeDoc.agent_id == agent_id) |
                     (models.KnowledgeDoc.agent_id.is_(None)))
    return q.order_by(models.KnowledgeDoc.agent_id.nullsfirst(),
                      models.KnowledgeDoc.created_at.desc()).all()


@router.post("/knowledge", response_model=schemas.KnowledgeOut)
def add_doc(data: schemas.KnowledgeCreate, db: Session = Depends(get_db)):
    if data.agent_id is not None and not db.get(models.Agent, data.agent_id):
        raise HTTPException(404, "Agent not found")
    doc = models.KnowledgeDoc(**data.model_dump())
    db.add(doc)
    db.commit()
    db.refresh(doc)
    try:
        embeddings.index_doc(db, doc)      # chunk + embed for retrieval
    except Exception:
        pass                                # KB still works via keyword fallback
    return doc


@router.post("/knowledge/upload", response_model=schemas.KnowledgeOut)
async def upload_doc(file: UploadFile = File(...),
                     agent_id: int | None = Form(default=None),
                     title: str | None = Form(default=None),
                     db: Session = Depends(get_db)):
    if agent_id is not None and not db.get(models.Agent, agent_id):
        raise HTTPException(404, "Agent not found")
    raw = await file.read()
    if len(raw) > MAX_DOC:
        raise HTTPException(400, "File too large (max 10 MB)")
    content = _extract_text(file.filename, raw).strip()
    if not content:
        raise HTTPException(400, "No extractable text found (scanned PDFs need OCR, not supported)")
    doc = models.KnowledgeDoc(agent_id=agent_id,
                              title=(title or file.filename)[:300], content=content)
    db.add(doc)
    db.commit()
    db.refresh(doc)
    try:
        embeddings.index_doc(db, doc)
    except Exception:
        pass
    return doc


@router.delete("/knowledge/{doc_id}", status_code=204)
def delete_doc(doc_id: int, db: Session = Depends(get_db)):
    doc = db.get(models.KnowledgeDoc, doc_id)
    if doc:
        db.query(models.KbChunk).filter(models.KbChunk.doc_id == doc_id).delete()
        db.delete(doc)
        db.commit()


@router.get("/templates", response_model=list[schemas.TemplateOut])
def list_templates(agent_id: int | None = Query(default=None),
                   db: Session = Depends(get_db)):
    q = db.query(models.Template)
    if agent_id is not None:
        q = q.filter((models.Template.agent_id == agent_id) |
                     (models.Template.agent_id.is_(None)))
    return q.order_by(models.Template.created_at.desc()).all()


@router.post("/templates", response_model=schemas.TemplateOut)
def add_template(data: schemas.TemplateCreate, db: Session = Depends(get_db)):
    t = models.Template(**data.model_dump())
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


@router.delete("/templates/{tpl_id}", status_code=204)
def delete_template(tpl_id: int, db: Session = Depends(get_db)):
    t = db.get(models.Template, tpl_id)
    if t:
        db.delete(t)
        db.commit()
