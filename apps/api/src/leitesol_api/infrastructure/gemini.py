from dataclasses import dataclass

from leitesol_agent.domain.usage import UsageMeter
from leitesol_agent.infrastructure.gemini import GeminiError, GeminiLanguageModel

from leitesol_api.infrastructure.azure_storage import get_key_vault_secret_provider
from leitesol_api.infrastructure.fabric import CATALOG_ENTITIES
from leitesol_api.infrastructure.settings import get_settings

__all__ = ["GeminiClient", "GeminiError", "GeminiPlan", "get_gemini_client"]


@dataclass(frozen=True, slots=True)
class GeminiPlan:
    entity: str
    answer: str
    limit: int
    order_by: str | None
    order_direction: str | None


class GeminiClient(GeminiLanguageModel):
    """Provedor do agente + o planejador de tabelas do mock inicial.

    As etapas do fluxo vigente (intenção, parâmetros, redação) vivem no
    módulo do agente. select_entity/plan_query são do navegador de tabelas e
    não são chamados por nenhuma rota.
    """

    def select_entity(self, question: str) -> str:
        entities = ", ".join(entity.name for entity in CATALOG_ENTITIES)
        prompt = (
            "You are a data catalog router for LeiteSol. Return only valid JSON with the "
            "key entity. Choose exactly one entity from this allowlist: "
            f"{entities}. "
            f"User question: {question}"
        )
        plan = self._generate_json(prompt)
        entity = plan.get("entity")
        if not isinstance(entity, str):
            raise GeminiError("Gemini returned an invalid entity selection.")
        if entity.lower() not in {item.name for item in CATALOG_ENTITIES}:
            raise GeminiError("Gemini selected an entity outside the allowlist.")
        return entity.lower()

    def plan_query(self, question: str, *, entity: str, columns: list[str]) -> GeminiPlan:
        if not columns:
            raise GeminiError("The selected entity has no columns available for querying.")

        column_list = ", ".join(columns)
        prompt = (
            "You are a safe SQL query planner for LeiteSol. Return only valid JSON with "
            "these keys: entity, answer, limit, orderBy and orderDirection. "
            f"The selected entity is {entity}. Its only valid columns are: {column_list}. "
            "entity must be exactly the selected entity. limit must be an integer from 1 to 100. "
            "orderBy must be one of the valid columns or null. "
            "orderDirection must be ASC, DESC or null. "
            "For requests for latest, last or most recent records, choose a date, timestamp or "
            "incremental "
            "identifier column when one exists and use DESC. Never invent columns or SQL. "
            "answer must be a concise Portuguese explanation of the planned query. "
            f"User question: {question}"
        )
        plan = self._generate_json(prompt)
        selected_entity = plan.get("entity")
        answer = plan.get("answer")
        limit = plan.get("limit")
        order_by = plan.get("orderBy")
        order_direction = plan.get("orderDirection")

        if selected_entity != entity or not isinstance(answer, str) or not isinstance(limit, int):
            raise GeminiError("Gemini returned an invalid query plan.")
        if not 1 <= limit <= 100:
            raise GeminiError("Gemini returned a query limit outside the allowed range.")
        if order_by is not None and (not isinstance(order_by, str) or order_by not in columns):
            raise GeminiError("Gemini selected an invalid ordering column.")
        if order_direction is not None and order_direction not in {"ASC", "DESC"}:
            raise GeminiError("Gemini selected an invalid ordering direction.")
        if order_by is None:
            order_direction = None
        elif order_direction is None:
            order_direction = "ASC"

        return GeminiPlan(
            entity=entity,
            answer=answer,
            limit=limit,
            order_by=order_by,
            order_direction=order_direction,
        )


def get_gemini_client(meter: UsageMeter | None = None) -> GeminiClient:
    settings = get_settings()
    api_key = settings.gemini_api_key
    if not api_key and settings.key_vault_url:
        api_key = get_key_vault_secret_provider().get_gemini_api_key(settings)
    return GeminiClient(api_key=api_key, model=settings.gemini_model, meter=meter)
