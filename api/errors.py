from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict


class ErrorCode(str, Enum):
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    UNSUPPORTED_FILE_TYPE = "UNSUPPORTED_FILE_TYPE"
    EMPTY_FILE = "EMPTY_FILE"
    PARSE_ERROR = "PARSE_ERROR"
    GRAPH_BUILD_FAILED = "GRAPH_BUILD_FAILED"
    VECTOR_INDEX_FAILED = "VECTOR_INDEX_FAILED"
    TIMEOUT = "TIMEOUT"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


@dataclass
class AppError(Exception):
    code: ErrorCode
    message: str
    detail: str = ""
    suggestion: str = ""
    status_code: int = 400

    def to_payload(self) -> Dict[str, Any]:
        return {
            "error": {
                "code": self.code.value,
                "message": self.message,
                "detail": self.detail,
                "suggestion": self.suggestion,
            }
        }


def error_payload(
    code: ErrorCode,
    message: str,
    detail: str = "",
    suggestion: str = "",
) -> Dict[str, Any]:
    return {
        "error": {
            "code": code.value,
            "message": message,
            "detail": detail,
            "suggestion": suggestion,
        }
    }
