"""공통 에러 계층 (지시서 §4.2).

성공이 아닌 모든 응답은 아래 한 가지 형태로 나간다:
    { "error": { "code": ..., "message": ..., "details": {...} } }

FastAPI 기본 HTTPException / RequestValidationError 도 같은 핸들러로 흡수한다.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    """애플리케이션 공통 에러. code / http_status / message / details 를 담는다."""

    code: str = "INTERNAL_ERROR"
    http_status: int = 500

    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        http_status: Optional[int] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if http_status is not None:
            self.http_status = http_status
        self.details = details or {}

    def to_response(self) -> JSONResponse:
        return JSONResponse(
            status_code=self.http_status,
            content={
                "error": {
                    "code": self.code,
                    "message": self.message,
                    "details": self.details,
                }
            },
        )


# --- 지시서 §4.2 표의 구체 에러들 ---
class ValidationFailed(AppError):
    code = "VALIDATION_FAILED"
    http_status = 400


class InvalidPin(AppError):
    code = "INVALID_PIN"
    http_status = 401


class SessionExpired(AppError):
    code = "SESSION_EXPIRED"
    http_status = 401


class NotFound(AppError):
    code = "NOT_FOUND"
    http_status = 404


class NoSourceFile(AppError):
    code = "NO_SOURCE_FILE"
    http_status = 404


class AlreadyConfirmed(AppError):
    code = "ALREADY_CONFIRMED"
    http_status = 409


class IpDuplicate(AppError):
    code = "IP_DUPLICATE"
    http_status = 409


class IpInactive(AppError):
    """비활성(deactive) IP로 새 계약을 만들려고 한 경우 (D-41).

    기존 계약(contractId 있음)에 draft·final 버전을 추가하는 것은 막지 않는다 —
    그 IP 연결은 계약이 처음 만들어질 때 이미 유효했고, 지금 하는 일은 그 계약의
    이력을 늘리는 것뿐이다. 새 계약 행을 만들 때(연장 포함, contractId 없음)만
    막는다 — "새 계약"은 항상 IP를 새로 연결하는 행위이기 때문이다.
    """

    code = "IP_INACTIVE"
    http_status = 409


class AssetInUse(AppError):
    """권리 대상(content_asset)을 더 이상 바꿀 수 없는 상태.

    두 경우를 같은 코드로 묶되 message 로 구분한다:
    ① rights_grant 가 참조 중 — 이미 판정된 권리의 대상 범위가 사후에 바뀌면
       판정 결과가 거짓이 된다(details.rightsGrantCount).
    ② IP 의 마지막 자산 — 사라지면 save_rights_batch() 의 기본 자산 조회가
       깨진다(details.assetCount).
    """

    code = "ASSET_IN_USE"
    http_status = 409


class AlreadyCancelled(AppError):
    code = "ALREADY_CANCELLED"
    http_status = 422


class ExtractNotReady(AppError):
    code = "EXTRACT_NOT_READY"
    http_status = 422


def register_error_handlers(app) -> None:
    """main.py 에서 한 번 호출. 모든 에러를 단일 형태로 변환한다."""

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return exc.to_response()

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        details: dict[str, Any] = {}
        errs = exc.errors()
        if errs:
            loc = ".".join(str(p) for p in errs[0].get("loc", []) if p != "body")
            details = {"field": loc}
        return ValidationFailed(
            "요청 형식이 올바르지 않습니다", details=details
        ).to_response()

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        # FastAPI 기본 HTTPException 이 새어나가도 공통 형태로 감싼다.
        code = {404: "NOT_FOUND", 401: "SESSION_EXPIRED"}.get(
            exc.status_code, "HTTP_ERROR"
        )
        return AppError(
            str(exc.detail), code=code, http_status=exc.status_code
        ).to_response()
