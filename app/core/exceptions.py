class HearingException(Exception):
    status_code: int = 400
    code: str = "HEARING_ERROR"

    def __init__(self, message: str, code: str | None = None):
        self.message = message
        if code:
            self.code = code
        super().__init__(message)


class AuthException(HearingException):
    status_code = 401
    code = "AUTH_ERROR"


class ForbiddenException(HearingException):
    status_code = 403
    code = "FORBIDDEN"


class NotFoundException(HearingException):
    status_code = 404
    code = "NOT_FOUND"


class ConflictException(HearingException):
    status_code = 409
    code = "CONFLICT"


class ValidationException(HearingException):
    status_code = 422
    code = "VALIDATION_ERROR"
