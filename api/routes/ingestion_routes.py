from typing import List

from fastapi import APIRouter, UploadFile, File, HTTPException

from api.controllers.ingestion_controller import (
    handle_upload,
    list_documents_controller,
    get_graph_data_controller,
    get_ingestion_status_controller,
    delete_document_controller,
)

router = APIRouter(tags=["Ingestion"])


@router.post("/upload")
def upload_route(files: List[UploadFile] = File(...)):
    try:
        # 控制器内部会将任务推送到 Celery，并返回排队结果
        return handle_upload(files)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/documents")
def list_documents_route():
    return list_documents_controller()


@router.get("/graph/data")
def get_graph_data_route():
    return get_graph_data_controller()


@router.get("/ingestion/status")
def get_ingestion_status_route():
    return get_ingestion_status_controller()


@router.delete("/documents/{filename}")
def delete_document_route(filename: str):
    try:
        return delete_document_controller(filename)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e))

