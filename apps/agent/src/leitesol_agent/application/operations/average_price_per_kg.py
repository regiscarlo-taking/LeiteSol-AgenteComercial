"""Preço médio geral por kg, calculado sobre os totais do período."""

from datetime import date
from typing import Any

from leitesol_agent.application.operations.base import (
    OperationResult,
    SqlFetcher,
    month_end_exclusive,
    month_start,
)
from leitesol_agent.application.operations.common import (
    FAT_KG,
    FAT_RS,
    HISTORY_START,
    UNIVERSE_FROM,
    last_closed_month,
    product_filter,
    product_question,
    round_kg,
    round_money,
    universe_where,
)
from leitesol_agent.application.operations.monthly_series import months_back
from leitesol_agent.domain.models import Notice, Operation, Parameter, Period, Scope

OPERATION_ID = "APP_PRICE_PER_KG"
INTENT_ID = "consultar_preco_medio_geral_por_kg"


def average_price_per_kg_operation() -> Operation:
    return Operation(
        operation_id=OPERATION_ID,
        skill_id="SK_LOCAL_ANALYTICS",
        intent_id=INTENT_ID,
        technical_name="consultar_preco_medio_geral_por_kg",
        business_intent=(
            "Calcular o preço médio geral em R$/kg no período pedido, dividindo a soma "
            "de FAT R$ pela soma de FAT KG no universo autorizado; não calcular média "
            "simples dos meses nem segmentar por cliente."
        ),
        alerts=(
            "FAT KG zero ou negativo impede o cálculo; retornar não calculável, nunca zero. "
            "Este resultado geral não substitui a análise comparativa por cliente da OP07."
        ),
        parameters=(
            Parameter(
                "janela_meses",
                "int",
                False,
                ">0",
                "6",
                "número positivo de competências completas",
            ),
            Parameter(
                "data_referencia",
                "date",
                False,
                "AAAA-MM-DD",
                None,
                "data que ancora a janela",
            ),
            Parameter(
                "filtro_produto",
                "string",
                False,
                "produto, família, grupamento ou subtotal cadastrado",
                None,
                "filtro de produto",
            ),
        ),
        examples=(
            "Qual foi o preço médio geral por quilo nos últimos 6 meses?",
            "Média de faturamento por kg nos últimos 3 meses",
            "Qual o R$/kg médio no semestre fechado?",
        ),
    )


def _period(
    window: int, reference: date | None, last_closed: date | None
) -> Period | None:
    if last_closed is None:
        return None
    last_closed_month_start = month_start(last_closed)
    anchor = month_start(reference) if reference else last_closed_month_start
    if anchor > last_closed_month_start:
        anchor = last_closed_month_start
    months = months_back(anchor, window)
    end_exclusive = month_end_exclusive(months[-1])
    return Period(
        start=months[0],
        end_exclusive=end_exclusive,
        partial=False,
        last_closed_month=last_closed.strftime("%Y-%m"),
    )


def build_query(
    start: date,
    end_exclusive: date,
    values: dict[str, Any],
    scope: Scope,
    product: tuple[str, list[Any]] | None = None,
) -> tuple[str, list[Any]]:
    where = universe_where(values, scope, product)
    sql = f"""
        SELECT SUM({FAT_RS}) AS fat_rs,
               SUM({FAT_KG}) AS fat_kg
        {UNIVERSE_FROM}
        WHERE f.Data >= ? AND f.Data < ?
{where.sql}
    """
    return sql, [start, end_exclusive, *where.params]


class AveragePricePerKg:
    operation_id = OPERATION_ID

    def run(
        self, fetcher: SqlFetcher, values: dict[str, Any], scope: Scope
    ) -> OperationResult:
        window = values.get("janela_meses", 6)
        if isinstance(window, bool) or not isinstance(window, int) or window <= 0:
            return OperationResult.clarification(
                "Informe um número positivo de competências fechadas para calcular o período."
            )

        last_closed = last_closed_month(fetcher)
        period = _period(window, values.get("data_referencia"), last_closed)
        if period is None:
            return OperationResult.clarification(
                "Não encontrei uma competência fechada no calendário para calcular o período."
            )

        product = None
        if values.get("filtro_produto"):
            product = product_filter(fetcher, values["filtro_produto"])
            if product is None:
                return OperationResult.clarification(product_question(values["filtro_produto"]))

        sql, params = build_query(
            period.start,
            period.end_exclusive,
            values,
            scope,
            product,
        )
        rows = fetcher.fetch(sql, tuple(params))
        row = rows[0] if rows else {}
        fat_rs = float(row.get("fat_rs") or 0)
        fat_kg = float(row.get("fat_kg") or 0)
        price_per_kg = round(fat_rs / fat_kg, 4) if fat_kg > 0 else None

        notices = []
        if fat_kg <= 0:
            notices.append(
                Notice(
                    "PRECO_MEDIO_NAO_CALCULAVEL",
                    "operacao",
                    "FAT KG total igual a zero ou negativo; o preço médio por kg não pode ser calculado.",
                )
            )
        if period.start < HISTORY_START:
            notices.append(
                Notice(
                    "BASE2025",
                    "base_historica",
                    "A base começa em janeiro de 2025; parte da janela solicitada pode não ter dados.",
                )
            )

        main_block = {
            "colunas": [
                {"id": "fat_rs", "rotulo": "FAT R$", "unidade": "R$"},
                {"id": "fat_kg", "rotulo": "FAT KG", "unidade": "KG"},
                {"id": "preco_medio_kg", "rotulo": "Preço médio", "unidade": "R$/kg"},
            ],
            "linhas": [
                {
                    "fat_rs": round_money(fat_rs),
                    "fat_kg": round_kg(fat_kg),
                    "preco_medio_kg": price_per_kg,
                }
            ],
        }
        return OperationResult(period=period, main_block=main_block, notices=notices)
