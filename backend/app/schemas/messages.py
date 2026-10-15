"""Message envelope (single source of truth: communications.models). TODO(P6): FastAPI response wrappers."""

from ..communications.models import Message, validate_known, validate_message

__all__ = ["Message", "validate_known", "validate_message"]
