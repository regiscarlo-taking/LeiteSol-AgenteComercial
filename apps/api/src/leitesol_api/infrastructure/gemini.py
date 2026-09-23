import json
from dataclasses import dataclass

import httpx

from leitesol_api.infrastructure.azure_storage import get_key_vault_secret_provider
from leitesol_api.infrastructure.fabric import CATALOG_ENTITIES
from leitesol_api.infrastructure.settings import get_settings


class GeminiError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class GeminiPlan:
    entity: str
    answer: str


class GeminiClient:
    def __init__(self, api_key: str, model: str) -> None:
        if not api_key:
            raise GeminiError("Gemini API key is not configured.")
        self._api_key = api_key
        self._model = model

    def plan_query(self, question: str) -> GeminiPlan:
        entities = ", ".join(entity.name for entity in CATALOG_ENTITIES)
        prompt = (
            "You are a SQL query planner for LeiteSol. Return only valid JSON with keys "
            "entity and answer. Choose exactly one entity from this allowlist: "
            f"{entities}. The answer must be a concise Portuguese explanation. "
            f"User question: {question}"
        )
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self._model}:generateContent?key={self._api_key}"
        )
        try:
            response = httpx.post(
                url,
                json={"contents": [{"parts": [{"text": prompt}]}]},
                timeout=30.0,
            )
            response.raise_for_status()
            text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
            plan = json.loads(text.strip().removeprefix("```json").removesuffix("```").strip())
        except (httpx.HTTPError, KeyError, IndexError, json.JSONDecodeError) as error:
            raise GeminiError("Gemini could not create a query plan.") from error

        entity = plan.get("entity")
        answer = plan.get("answer")
        if not isinstance(entity, str) or not isinstance(answer, str):
            raise GeminiError("Gemini returned an invalid query plan.")
        if entity.lower() not in {item.name for item in CATALOG_ENTITIES}:
            raise GeminiError("Gemini selected an entity outside the allowlist.")
        return GeminiPlan(entity=entity.lower(), answer=answer)


def get_gemini_client() -> GeminiClient:
    settings = get_settings()
    api_key = settings.gemini_api_key
    if not api_key and settings.key_vault_url:
        api_key = get_key_vault_secret_provider().get_gemini_api_key(settings)
    return GeminiClient(api_key=api_key, model=settings.gemini_model)
