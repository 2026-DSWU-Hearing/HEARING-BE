from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.exceptions import HearingException


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(HearingException)
    async def hearing_exception_handler(request: Request, exc: HearingException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message},
        )
