import asyncio
from datetime import datetime

import httpx

from leitesol_api import main
from leitesol_agent.application.answer_question import AnswerQuestion
from leitesol_agent.application.operations import OPERATION_HANDLERS
from leitesol_agent.domain.models import Scope
from leitesol_api.infrastructure.auth import TokenData, verify_token
from leitesol_api.interfaces.http.routes import questions
from leitesol_api.interfaces.http.routes.chat import to_chat_payload
from test_agent import SELLER_SCOPE, FakeCatalog, FakeFetcher, FakeLLM, FixedScope, answer


def post_chat(use_case_factory) -> httpx.Response:
    main.app.dependency_overrides[verify_token] = lambda: TokenData(username="t", full_access=True)
    main.app.dependency_overrides[questions.answer_question_factory] = lambda: use_case_factory

    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            return await client.post("/chat/query", json={"question": "pedidos em aberto?"})

    try:
        return asyncio.run(send())
    finally:
        main.app.dependency_overrides.clear()


def test_answered_response_becomes_text_and_table() -> None:
    fetcher = FakeFetcher(
        [
            [{"UltimaFechada": datetime(2026, 8, 1)}],
            [{"TemParcial": 0}],
            [{"fat_rs_atual": 200.0, "fat_rs_anterior": 100.0, "fat_kg_atual": 20.0, "fat_kg_anterior": 10.0}],
        ]
    )
    llm = FakeLLM("comparar_vendas_ano_anterior", {"periodo_inicio": "2026-06-01", "periodo_fim": "2026-06-30"})
    payload = to_chat_payload(answer(llm, SELLER_SCOPE, fetcher))

    assert payload["answer"].startswith("Resumo.")
    table = payload["sqlResult"]
    assert table["sql"] is None
    assert table["rowCount"] == len(table["rows"]) == 1
    # A tela indexa cada linha pelo rótulo da coluna.
    assert set(table["rows"][0]) == set(table["columns"])


def test_chat_route_uses_the_catalog_flow() -> None:
    use_case = AnswerQuestion(
        catalog=FakeCatalog(),
        scopes=FixedScope(Scope(sees_everything=True)),
        llm=FakeLLM(None),
        fetcher=FakeFetcher(),
        handlers=OPERATION_HANDLERS,
    )
    response = post_chat(lambda: use_case)

    assert response.status_code == 200
    body = response.json()
    assert body["metadata"]["status"] == "fora_de_escopo"
    assert "fora do que o agente responde" in body["data"]["answer"]
    assert body["data"]["sqlResult"]["rows"] == []


def test_chat_route_hides_technical_failure() -> None:
    def broken():
        raise RuntimeError("segredo interno")

    response = post_chat(broken)

    assert response.status_code == 503
    assert "segredo" not in response.text
    assert response.json()["data"]["answer"].startswith("Não foi possível responder")
