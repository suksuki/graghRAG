"""文档中心、向量搜索、实体档案（P0 产品化）。"""

from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Query, Request

from api.controllers.knowledge_hub_controller import (
    get_entity_profile_controller,
    get_product_document_controller,
    list_product_documents_controller,
    search_chunks_controller,
)

router = APIRouter(tags=["knowledge"])


@router.get("/docs")
def list_product_docs():
    return list_product_documents_controller()


@router.get("/docs/{doc_id:path}")
def get_product_doc_detail(doc_id: str, request: Request):
    decoded = unquote(doc_id or "").strip()
    lang = (request.headers.get("x-lang") or "zh").strip().lower()
    data = get_product_document_controller(decoded, lang=lang)
    if data is None:
        raise HTTPException(status_code=404, detail="文档不存在或路径不合法")
    return data


@router.get("/search")
def search_knowledge(
    q: str = Query("", description="检索关键词"),
    top_k: int = Query(10, ge=1, le=30),
):
    return search_chunks_controller(query=q, top_k=top_k)


@router.get("/entity/{name:path}")
def get_entity_profile(name: str, request: Request):
    decoded = unquote(name or "").strip()
    lang = (request.headers.get("x-lang") or "zh").strip().lower()
    data = get_entity_profile_controller(decoded, lang=lang)
    if data is None:
        raise HTTPException(status_code=404, detail="未找到该实体")
    return data
