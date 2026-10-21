"""Busca de cliente/rede pelo nome digitado (application/client_names.py).

Casos tirados da conferência de 19-10 (sql/45): Assaí e Carrefour batem com
o grupo de venda; Granfood só com o nome da rede; Megatop e "G Barbosa" só
por trecho. Funções de teste soltas; banco = fixture `fake_fetcher`.
"""

from datetime import date, datetime
from types import SimpleNamespace

from leitesol_agent.application.answer_question import AnswerQuestion
from leitesol_agent.application.client_names import is_name, resolve_client_names
from leitesol_agent.application.operations.common import client_filter, universe_where
from leitesol_agent.application.operations.purchase_frequency import PurchaseFrequency
from leitesol_agent.domain.models import (
    Catalog,
    Operation,
    Parameter,
    ResponseStatus,
    Scope,
)

FULL = Scope(sees_everything=True)
CARTEIRA = Scope(sees_everything=False, sellers=frozenset({"000123"}), teams=frozenset({"997"}))


def rede(code: str, name: str, stores: int, group: int = 0) -> dict:
    return {"rede": code, "nome": name + "   ", "lojas": stores, "grupo_exato": group}


# --- resolução --------------------------------------------------------------------


def test_exact_sales_group_wins_over_other_networks(fake_fetcher) -> None:
    exact = [rede("000487", "ASSAI", 60, group=1), rede("75087379", "ASSAI", 1)]
    fetcher = fake_fetcher([exact])
    values = {"escopo_cliente": "Assaí"}

    resolution = resolve_client_names(fetcher, values, FULL)

    assert resolution.question is None
    assert values["escopo_cliente"] == "rede:000487"
    assert "ASSAI (rede 000487, 60 loja(s))" in resolution.notices[0].text
    sql, params = fetcher.calls[0]
    assert params == ("ASSAI", "ASSAI", "ASSAI")  # sem acento, como vw_produto_termo
    assert len(fetcher.calls) == 1  # achou no exato: não faz a busca por trecho


def test_network_name_without_sales_group(fake_fetcher) -> None:
    fetcher = fake_fetcher([[rede("07798373", "GRANFOOD", 1)]])
    values = {"escopo_cliente": "Granfood"}

    resolve_client_names(fetcher, values, FULL)

    assert values["escopo_cliente"] == "rede:07798373"


def test_partial_name_with_single_network(fake_fetcher) -> None:
    fetcher = fake_fetcher([[], [rede("000036", "G BARBOSA /CENCOSUD", 29)]])
    values = {"escopo_cliente": "G Barbosa"}

    resolution = resolve_client_names(fetcher, values, FULL)

    assert values["escopo_cliente"] == "rede:000036"
    assert resolution.notices[0].code == "CLIENTE_RESOLVIDO"
    sql, params = fetcher.calls[1]
    assert "LIKE ? ESCAPE" in sql
    assert params == ("%G BARBOSA%",) * 3


def test_partial_name_with_several_networks_asks(fake_fetcher) -> None:
    options = [rede("13004742", "G BARBOSA -SERGIPE", 3), rede("000036", "G BARBOSA /CENCOSUD", 29)]
    fetcher = fake_fetcher([[], options])
    values = {"cliente_rede": "Barbosa"}

    resolution = resolve_client_names(fetcher, values, FULL)

    assert values["cliente_rede"] == "Barbosa"  # nada é escolhido em silêncio
    assert resolution.question.index("000036") < resolution.question.index("13004742")
    assert "Qual deles?" in resolution.question


def test_several_exact_networks_also_ask(fake_fetcher) -> None:
    fetcher = fake_fetcher([[rede("1", "IDEAL", 2), rede("2", "IDEAL", 1)]])
    assert resolve_client_names(fetcher, {"escopo_cliente": "Ideal"}, FULL).question


def test_unknown_name_asks_for_another_identification(fake_fetcher) -> None:
    resolution = resolve_client_names(fake_fetcher([[], []]), {"escopo_cliente": "Xpto"}, FULL)
    assert "Não encontrei" in resolution.question


def test_codes_and_cnpj_skip_the_search(fake_fetcher) -> None:
    fetcher = fake_fetcher([])
    values = {"escopo_cliente": "17351", "cliente_rede": "12.345.678/0001-99", "cliente_loja": None}

    resolution = resolve_client_names(fetcher, values, FULL)

    assert fetcher.calls == []
    assert resolution.notices == []
    assert values["escopo_cliente"] == "17351"
    assert not is_name("000534")


def test_search_stays_inside_the_user_portfolio(fake_fetcher) -> None:
    fetcher = fake_fetcher([[], []])
    resolve_client_names(fetcher, {"escopo_cliente": "Megatop"}, CARTEIRA)
    for sql, params in fetcher.calls:
        assert "c.RCAAtual IN (?)" in sql
        assert params[-1] == "000123"


def test_like_wildcards_typed_by_the_user_are_literal(fake_fetcher) -> None:
    fetcher = fake_fetcher([[], []])
    resolve_client_names(fetcher, {"escopo_cliente": "50%_OFF"}, FULL)
    assert fetcher.calls[1][1][0] == "%50\\%\\_OFF%"


# --- filtro com a rede resolvida ------------------------------------------------------


def test_resolved_network_filters_only_by_network() -> None:
    clause, params = client_filter("rede:000487")
    assert clause == "c.Rede = ?"
    assert params == ["000487"]


def test_store_parameter_accepts_resolved_network() -> None:
    where = universe_where({"cliente_loja": "rede:07798373"}, FULL)
    assert "c.Rede = ?" in where.sql
    assert "07798373" in where.params


# --- fluxo da pergunta ------------------------------------------------------------------


def frequency_flow(fetcher, scope: Scope = FULL):
    operation = Operation(
        "OP06",
        "SK02",
        "analisar_frequencia_recencia_cliente",
        "calcular_frequencia_recencia",
        "Frequência",
        None,
        (Parameter("escopo_cliente", "string", True, None, None, "Cliente"),),
    )
    llm = SimpleNamespace(
        classify_intent=lambda question, catalog: operation.intent_id,
        extract_parameters=lambda question, op, today: {"escopo_cliente": "Megatop"},
        compose_narrative=lambda question, op, contract: "Resumo.",
    )
    return AnswerQuestion(
        catalog=SimpleNamespace(get=lambda: Catalog((operation,), {})),
        scopes=SimpleNamespace(resolve=lambda email, full_access: scope),
        llm=llm,
        fetcher=fetcher,
        handlers={"OP06": PurchaseFrequency()},
        today=lambda: date(2026, 10, 19),
    ).execute(
        question="Frequência da Megatop?", email="a@b.com", full_access=True, correlation_id="c1"
    )


def test_flow_resolves_the_name_before_running_the_operation(fake_fetcher) -> None:
    megatop = [rede("55032745", "MEGATOP DISTRIBUIDOR", 1)]
    fetcher = fake_fetcher([[], megatop, [{"UltimaFechada": datetime(2026, 7, 31)}], []])

    response = frequency_flow(fetcher)

    assert response.status is ResponseStatus.ANSWERED
    assert response.parameters["escopo_cliente"] == "rede:55032745"
    assert "CLIENTE_RESOLVIDO" in {notice.code for notice in response.notices}
    sql, params = fetcher.calls[-1]
    assert "c.Rede = ?" in sql
    assert "55032745" in params


def test_flow_returns_the_question_when_the_name_is_ambiguous(fake_fetcher) -> None:
    options = [rede("1", "MEGATOP A", 1), rede("2", "MEGATOP B", 1)]
    response = frequency_flow(fake_fetcher([[], options]))

    assert response.status is ResponseStatus.CLARIFICATION
    assert "MEGATOP A" in response.question_to_user
