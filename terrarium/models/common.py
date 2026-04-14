"""Common models shared across modules."""
from __future__ import annotations
import traceback as tb_module
from pydantic import BaseModel


class ExceptionInfo(BaseModel):
    """Captured exception details."""
    exception_type: str
    exception_message: str
    exception_traceback: str

    @classmethod
    def from_exception(cls, e: BaseException) -> ExceptionInfo:
        return cls(
            exception_type=type(e).__name__,
            exception_message=str(e),
            exception_traceback=tb_module.format_exc(),
        )
