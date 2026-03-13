from typing import Dict, Optional

from fastapi import APIRouter

from api.schemas import TestRequest
from api.controllers.settings_controller import (
    get_app_settings,
    test_connection_controller,
    get_ollama_models_controller,
    update_settings_controller,
)

router = APIRouter(tags=["Settings"])


@router.get("/settings")
def get_settings_route():
    return get_app_settings()


@router.post("/settings/test")
async def test_settings_route(
    test_req: Optional[TestRequest] = None,
    type: Optional[str] = None,
    url: Optional[str] = None,
):
    return await test_connection_controller(test_req, type, url)


@router.get("/ollama/models")
async def get_ollama_models_route(url: Optional[str] = None):
    return await get_ollama_models_controller(url)


@router.post("/settings/update")
async def update_settings_route(update: Dict[str, str]):
    return await update_settings_controller(update)

