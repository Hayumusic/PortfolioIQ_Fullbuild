from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from app.core.logging import get_logger

ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


class StructuredAIClient(Protocol):
    async def analyze_json(
        self,
        *,
        instructions: str,
        evidence: list[dict[str, Any]],
        response_model: type[ResponseModel],
    ) -> ResponseModel: ...


class OpenAIServiceUnavailable(RuntimeError):
    pass


class OpenAIService:
    """Central boundary for future structured OpenAI calls.

    Analysis modules depend on this service rather than an SDK or API route. The
    initial scaffold intentionally performs no external AI requests.
    """

    def __init__(self, api_key: str | None, model: str | None) -> None:
        self.api_key = api_key
        self.model = model
        self.logger = get_logger(__name__)

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.model)

    async def analyze_json(
        self,
        *,
        instructions: str,
        evidence: list[dict[str, Any]],
        response_model: type[ResponseModel],
    ) -> ResponseModel:
        self.logger.info(
            "AI analysis requested model=%s evidence_items=%d response_schema=%s",
            self.model or "not-configured",
            len(evidence),
            response_model.__name__,
        )
        raise OpenAIServiceUnavailable(
            "OpenAI execution is not implemented in the initial backend scaffold"
        )
