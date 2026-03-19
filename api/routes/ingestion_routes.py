from typing import List

from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
import logging

from api.controllers.ingestion_controller import (
    handle_upload,
    list_documents_controller,
    get_graph_data_controller,
    get_ingestion_status_controller,
    get_ingest_job_status_controller,
    delete_document_controller,
)
from api.errors import AppError, ErrorCode, error_payload

router = APIRouter(tags=["Ingestion"])
logger = logging.getLogger(__name__)


@router.post("/upload")
def upload_route(files: List[UploadFile] = File(...)):
    try:
        # 控制器内部会将任务推送到 Celery，并返回排队结果
        return handle_upload(files)
    except AppError as e:
        logger.warning("Upload rejected (%s): %s", e.status_code, e.detail or e.message)
        return JSONResponse(status_code=e.status_code, content=e.to_payload())
    except Exception as e:  # noqa: BLE001
        logger.exception("Upload failed (500): %s", str(e))
        payload = error_payload(
            ErrorCode.UNKNOWN_ERROR,
            "上传失败",
            str(e),
            "请稍后重试，若持续失败请联系管理员",
        )
        return JSONResponse(status_code=500, content=payload)


@router.get("/documents")
def list_documents_route():
    return list_documents_controller()


@router.get("/graph/data")
def get_graph_data_route():
    return get_graph_data_controller()


@router.get("/ingestion/status")
def get_ingestion_status_route():
    return get_ingestion_status_controller()


@router.get("/ingest/status")
def get_ingest_job_status_route(job_id: str):
    return get_ingest_job_status_controller(job_id)


@router.delete("/documents/{filename}")
def delete_document_route(filename: str):
    try:
        return delete_document_controller(filename)
    except FileNotFoundError as e:
        return JSONResponse(
            status_code=404,
            content=error_payload(
                ErrorCode.PARSE_ERROR,
                "文件不存在",
                str(e),
                "请刷新文档列表后重试",
            ),
        )
    except Exception as e:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=error_payload(
                ErrorCode.UNKNOWN_ERROR,
                "删除文档失败",
                str(e),
                "请稍后重试",
            ),
        )

