"""Apoio comum aos testes do agente: banco falso sem classe de teste.

`fake_fetcher(respostas)` devolve um objeto com `.fetch(sql, params)` que
entrega as respostas na ordem das chamadas, guarda cada chamada em `.calls`
e confere que cada `?` do SQL tem um parâmetro - erro de alinhamento entre
placeholder e valor quebra o teste em vez de chegar ao Warehouse.
"""

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest


def build_fake_fetcher(responses: list[list[dict[str, Any]]]) -> SimpleNamespace:
    pending = list(responses)
    calls: list[tuple[str, tuple[Any, ...]]] = []

    def fetch(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        assert sql.count("?") == len(params), (
            f"{sql.count('?')} placeholders x {len(params)} params"
        )
        calls.append((sql, params))
        return pending.pop(0) if pending else []

    return SimpleNamespace(fetch=fetch, calls=calls)


@pytest.fixture
def fake_fetcher() -> Callable[[list[list[dict[str, Any]]]], SimpleNamespace]:
    return build_fake_fetcher
