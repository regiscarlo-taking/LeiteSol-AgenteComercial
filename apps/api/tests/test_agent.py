import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from leitesol_api import main
from leitesol_api.application.answer_question import AnswerQuestion
from leitesol_api.application.operations import OPERATION_HANDLERS
from leitesol_api.application.operations.compare_previous_year import (
    build_query,
    resolve_period,
    shape_rows,
)
from leitesol_api.application.parameters import validate_parameters
from leitesol_api.domain.agent import Catalog, Operation, Parameter, ResponseStatus, Scope
from leitesol_api.infrastructure import auth
from leitesol_api.infrastructure.auth import TokenData, verify_token
from leitesol_api.infrastructure.catalog import build_catalog
from leitesol_api.infrastructure.scope import ScopeResolver
from leitesol_api.infrastructure.settings import Settings
from leitesol_api.interfaces.http.routes import questions

OP12 = Operation(
    operation_id="OP12",
    skill_id="SK02",
    intent_id="comparar_vendas_ano_anterior",
    technical_name="comparar_ano_anterior",
    business_intent="Comparar o periodo solicitado com o intervalo equivalente do ano anterior",
    alerts="Mes vigente so entra com aviso de parcialidade.",
    parameters=(
        Parameter("periodo_inicio", "date", True, "AAAA-MM-DD", None, "Inicio do intervalo"),
        Parameter("periodo_fim", "date", True, "AAAA-MM-DD", None, "Fim do intervalo"),
        Parameter("metrica", "enum", False, "fat_rs|fat_kg|fat_tons|ambas", "ambas", "Metrica"),
        Parameter("uf", "string", False, "BISA1.A1_EST", None, "UF"),
        Parameter(
            "granularidade",
            "enum",
            False,
            "total|cliente|produto|vendedor|uf|municipio|segmento",
            None,
            "Detalhamento",
        ),
        Parameter("situacao", "enum", False, "crescimento|queda|igual|todas", "todas", "Direcao"),
    ),
)
OP05 = Operation("OP05", "SK04", "classificar_curva_abc_cliente", "abc", "Curva ABC", None)
CATALOG = Catalog(operations=(OP05, OP12), transversal_rules={})
SELLER_SCOPE = Scope(sees_everything=False, sellers=frozenset({"000123", "000456"}), teams=frozenset({"997"}))


class FakeFetcher:
    def __init__(self, responses: list[list[dict[str, Any]]] | None = None) -> None:
        self.responses = list(responses or [])
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def fetch(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        self.calls.append((sql, params))
        return self.responses.pop(0) if self.responses else []


class FakeLLM:
    def __init__(self, intent: str | None, parameters: dict[str, Any] | None = None) -> None:
        self.intent = intent
        self.parameters = parameters or {}
        self.composed_with: dict[str, Any] | None = None

    def classify_intent(self, question: str, catalog: Catalog) -> str | None:
        return self.intent

    def extract_parameters(self, question: str, operation: Operation, today: date) -> dict[str, Any]:
        return self.parameters

    def compose_narrative(self, question: str, operation: Operation, contract: dict[str, Any]) -> str:
        self.composed_with = contract
        return "Resumo."


class FakeCatalog:
    def get(self) -> Catalog:
        return CATALOG


class FixedScope:
    def __init__(self, scope: Scope | None) -> None:
        self.scope = scope

    def resolve(self, *, email: str | None, full_access: bool) -> Scope | None:
        return self.scope


def answer(llm: FakeLLM, scope: Scope | None, fetcher: FakeFetcher | None = None):
    return AnswerQuestion(
        catalog=FakeCatalog(),
        scopes=FixedScope(scope),
        llm=llm,
        fetcher=fetcher or FakeFetcher(),
        handlers=OPERATION_HANDLERS,
    ).execute(question="?", email="a@b.com", full_access=False, correlation_id="c1")


# ------------------------------------------------------------------ parâmetros

def test_missing_period_asks_the_user_once() -> None:
    result = validate_parameters(OP12, {"metrica": "fat_kg"})

    assert not result.is_complete
    assert len(result.questions) == 1
    assert "período" in result.questions[0]


def test_enum_outside_domain_asks_instead_of_guessing() -> None:
    result = validate_parameters(
        OP12, {"periodo_inicio": "2026-01-01", "periodo_fim": "2026-06-30", "metrica": "margem"}
    )

    assert not result.is_complete


def test_defaults_are_applied() -> None:
    result = validate_parameters(OP12, {"periodo_inicio": "2026-01-01", "periodo_fim": "2026-06-30"})

    assert result.is_complete
    assert result.values["metrica"] == "ambas"
    assert result.values["periodo_inicio"] == date(2026, 1, 1)


# ------------------------------------------------------------------ OP12

def test_period_is_normalized_to_whole_months_and_shifted_one_year() -> None:
    period, adjusted = resolve_period(
        {"periodo_inicio": date(2026, 1, 15), "periodo_fim": date(2026, 6, 10)}
    )

    assert adjusted
    assert (period.start, period.end_exclusive) == (date(2026, 1, 1), date(2026, 7, 1))
    assert (period.comparison_start, period.comparison_end_exclusive) == (
        date(2025, 1, 1),
        date(2025, 7, 1),
    )


def test_query_applies_universe_filters_and_scope() -> None:
    period, _ = resolve_period({"periodo_inicio": date(2026, 6, 1), "periodo_fim": date(2026, 6, 30)})
    plan = build_query({"granularidade": "uf", "uf": "sp"}, period, SELLER_SCOPE)

    assert "p.FlagProdutoAcabado = 1" in plan.sql  # RT13
    assert "c.FlagExterior = 0" in plan.sql  # RT14
    assert "f.VendedorId IN (?, ?)" in plan.sql  # RT34
    assert "GROUP BY c.UF" in plan.sql
    assert plan.sql.count("?") == len(plan.params)
    assert "SP" in plan.params
    assert {"000123", "000456"} <= set(plan.params)


def test_full_scope_has_no_seller_filter() -> None:
    period, _ = resolve_period({"periodo_inicio": date(2026, 6, 1), "periodo_fim": date(2026, 6, 30)})
    plan = build_query({}, period, Scope(sees_everything=True))

    assert "VendedorId IN" not in plan.sql
    assert plan.sql.count("?") == len(plan.params)


def test_zero_base_goes_to_exceptions_without_percentage() -> None:
    rows = [
        {"uf": "SP", "fat_rs_atual": 150.0, "fat_rs_anterior": 100.0, "fat_kg_atual": 10.5, "fat_kg_anterior": 8.0},
        {"uf": "MG", "fat_rs_atual": 80.0, "fat_rs_anterior": 0.0, "fat_kg_atual": 3.0, "fat_kg_anterior": 0.0},
    ]
    main_block, exceptions, total = shape_rows(rows, (("c.UF", "uf", "UF"),), "ambas", "todas")

    assert total == 1
    line = main_block["linhas"][0]
    assert line["fat_rs_variacao_pct"] == 50.0
    assert line["fat_kg_atual"] == 11  # RT16: 10,5 sobe
    assert exceptions[0]["linhas"][0]["uf"] == "MG"
    assert exceptions[0]["linhas"][0]["fat_rs_variacao_pct"] is None


# ------------------------------------------------------------------ fluxo

def test_user_without_scope_gets_no_data() -> None:
    fetcher = FakeFetcher()
    response = answer(FakeLLM("comparar_vendas_ano_anterior"), None, fetcher)

    assert response.status is ResponseStatus.NO_SCOPE
    assert fetcher.calls == []


def test_unknown_intent_is_out_of_scope() -> None:
    assert answer(FakeLLM(None), SELLER_SCOPE).status is ResponseStatus.OUT_OF_SCOPE


def test_operation_without_handler_is_declared_unavailable() -> None:
    response = answer(FakeLLM("classificar_curva_abc_cliente"), SELLER_SCOPE)

    assert response.status is ResponseStatus.ERROR
    assert response.operation is OP05


def test_missing_parameter_becomes_clarification() -> None:
    response = answer(FakeLLM("comparar_vendas_ano_anterior", {}), SELLER_SCOPE)

    assert response.status is ResponseStatus.CLARIFICATION
    assert response.question_to_user


def test_answered_envelope_follows_contract() -> None:
    fetcher = FakeFetcher(
        [
            [{"UltimaFechada": datetime(2026, 8, 1)}],
            [{"TemParcial": 0}],
            [{"fat_rs_atual": 200.0, "fat_rs_anterior": 100.0, "fat_kg_atual": 20.0, "fat_kg_anterior": 10.0}],
        ]
    )
    llm = FakeLLM(
        "comparar_vendas_ano_anterior",
        {"periodo_inicio": "2026-06-01", "periodo_fim": "2026-06-30"},
    )
    response = answer(llm, SELLER_SCOPE, fetcher)
    contract = response.to_contract()

    assert contract["status"] == "respondida"
    assert contract["operacao"]["id"] == "OP12"
    assert contract["periodo"]["fim_exibicao"] == "2026-06-30"
    assert contract["periodo"]["ultima_competencia_fechada"] == "2026-08"
    assert contract["recorte"]["descricao"] == "dentro da sua carteira"
    assert {notice["codigo"] for notice in contract["avisos"]} >= {"RT17", "OP12"}
    assert contract["narrativa"] == "Resumo."
    # A redação recebe o resultado agregado, não a pergunta crua sozinha.
    assert llm.composed_with["dados"]["principal"]["linhas"][0]["fat_rs_atual"] == 200.0


# ------------------------------------------------------------------ alçada

def test_scope_uses_email_and_keeps_team_code_as_seller() -> None:
    fetcher = FakeFetcher([[{"EquipeId": "967", "RepresentanteId": None}, {"EquipeId": "997", "RepresentanteId": "000123"}]])
    scope = ScopeResolver(fetcher).resolve(email=" Gestor@LeiteSol.com.br ", full_access=False)

    assert fetcher.calls[0][1] == ("gestor@leitesol.com.br",)
    assert scope.sellers == frozenset({"967", "997", "000123"})


def test_scope_without_grant_is_none() -> None:
    assert ScopeResolver(FakeFetcher([[]])).resolve(email="x@y.com", full_access=False) is None


def test_full_access_skips_lookup() -> None:
    fetcher = FakeFetcher()
    scope = ScopeResolver(fetcher).resolve(email=None, full_access=True)

    assert scope.sees_everything
    assert fetcher.calls == []


def test_catalog_marks_only_s_as_required() -> None:
    catalog = build_catalog(
        [{"operacao_id": "OP12", "skill_id": "SK02", "intencao_id": "x", "nome_tecnico": "y", "intencao_negocio": "z", "alertas": " "}],
        [
            {"operacao_id": "OP12", "parametro": "a", "tipo": "date", "obrigatorio": "S", "dominio_valores": None, "valor_default": "", "descricao": None},
            {"operacao_id": "OP12", "parametro": "b", "tipo": "enum", "obrigatorio": "Condicional", "dominio_valores": "p|q", "valor_default": "p", "descricao": None},
        ],
        [],
        [],
    )
    operation = catalog.operations[0]

    assert operation.alerts is None
    assert [p.required for p in operation.parameters] == [True, False]
    assert operation.parameters[1].enum_values == ("p", "q")


# ------------------------------------------------------------------ Entra ID

@pytest.fixture
def entra(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    settings = Settings(
        environment="production",
        entra_tenant_id="tenant",
        entra_api_audience="api://leitesol",
        entra_full_access_group_ids="grupo-diretoria",
    )
    monkeypatch.setattr(auth, "get_settings", lambda: settings)

    class Jwks:
        def get_signing_key_from_jwt(self, token):
            return type("Key", (), {"key": key.public_key()})()

    monkeypatch.setattr(auth, "_entra_jwks_client", lambda tenant: Jwks())

    def sign(**claims):
        payload = {
            "aud": "api://leitesol",
            "iss": "https://login.microsoftonline.com/tenant/v2.0",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
            "preferred_username": "Gestor@LeiteSol.com.br",
            "oid": "oid-1",
            **claims,
        }
        return jwt.encode(payload, key, algorithm="RS256")

    return sign


def test_entra_token_yields_email(entra) -> None:
    user = auth.verify_token(entra())

    assert user.email == "gestor@leitesol.com.br"
    assert not user.full_access


def test_entra_group_grants_full_access(entra) -> None:
    assert auth.verify_token(entra(groups=["grupo-diretoria"])).full_access


@pytest.mark.parametrize(
    "claims",
    [{"aud": "outra-api"}, {"iss": "https://login.microsoftonline.com/outro/v2.0"}],
)
def test_entra_token_for_other_audience_or_tenant_is_rejected(entra, claims) -> None:
    with pytest.raises(auth.HTTPException):
        auth.verify_token(entra(**claims))


def test_local_login_is_refused_outside_development() -> None:
    with pytest.raises(ValueError):
        Settings(environment="staging", auth_mode="local")


# ------------------------------------------------------------------ rota

def test_questions_route_returns_contract_envelope() -> None:
    llm = FakeLLM(None)
    use_case = AnswerQuestion(
        catalog=FakeCatalog(),
        scopes=FixedScope(Scope(sees_everything=True)),
        llm=llm,
        fetcher=FakeFetcher(),
        handlers=OPERATION_HANDLERS,
    )
    main.app.dependency_overrides[verify_token] = lambda: TokenData(username="t", full_access=True)
    main.app.dependency_overrides[questions.answer_question_factory] = lambda: (lambda: use_case)

    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            return await client.post("/perguntas", json={"pergunta": "pedidos em aberto?"})

    try:
        response = asyncio.run(send())
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "fora_de_escopo"
