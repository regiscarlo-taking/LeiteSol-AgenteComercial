"""Filtro de produto por lista fechada + sinônimos do glossário (RT35).

Caso de origem: homologação de 21-10 (AIC-294) - "bolsa" não estava na
vw_produto_termo e o agente não consultava o AGT_GLOSSARIO, então perguntava
em vez de filtrar. Termos e sinônimos tirados da V2 e do glossário reais.
Funções de teste soltas; banco = fixture `fake_fetcher`.
"""

from leitesol_agent.application.operations.common import (
    PRODUCT_SYNONYMS_SQL,
    match_phrases,
    product_filter,
)

NO_TREE: list[dict] = []
TERMS = [
    {"TermoNormalizado": term}
    for term in ("GRANEL", "SACO", "FARDO", "PACOTE", "ALMOFADA", "PO", "LA SERENISSIMA",
                 "25 KG", "DOCE", "ZERO LACTOSE")
]
GLOSSARY = [
    {"termo": "granel", "sinonimos": "granel;bolsa;saco;big bag;fardo;saco de 25 kg;25 kg"},
    {"termo": "almofada", "sinonimos": "almofada;almofadinha;pacote;sache"},
    {"termo": "zero lactose", "sinonimos": "zero lactose;sem lactose;baixa lactose"},
    {"termo": "marca", "sinonimos": "marca;serenissima;leite sol"},  # termo fora da lista
]


def terms_of(result) -> list:
    clause, params = result
    return params[:-1]


def test_term_in_list_needs_no_glossary(fake_fetcher) -> None:
    fetcher = fake_fetcher([NO_TREE, TERMS])

    result = product_filter(fetcher, "Doce")

    assert terms_of(result) == ["DOCE"]
    assert len(fetcher.calls) == 2  # árvore + lista; glossário não é lido


def test_bolsa_resolves_to_granel_through_glossary(fake_fetcher) -> None:
    fetcher = fake_fetcher([NO_TREE, TERMS, GLOSSARY])

    clause, params = product_filter(fetcher, "bolsa")

    assert params == ["GRANEL", 1]
    assert fetcher.calls[2][0] == PRODUCT_SYNONYMS_SQL
    assert "HAVING COUNT(DISTINCT t.TermoNormalizado) = ?" in clause


def test_multiword_term_and_synonym_phrase(fake_fetcher) -> None:
    fetcher = fake_fetcher([NO_TREE, TERMS, GLOSSARY])

    result = product_filter(fetcher, "pó La Serenissima sem lactose")

    assert terms_of(result) == ["LA SERENISSIMA", "PO", "ZERO LACTOSE"]


def test_longest_phrase_wins() -> None:
    phrases = {"SACO": "SACO", "25 KG": "25 KG", "SACO DE 25 KG": "GRANEL"}

    assert match_phrases("SACO DE 25 KG", phrases) == ["GRANEL"]
    assert match_phrases("SACO 25 KG", phrases) == ["25 KG", "SACO"]


def test_synonym_that_is_a_listed_term_keeps_its_own_meaning(fake_fetcher) -> None:
    # "pacote" é sinônimo de almofada no glossário, mas também é termo da V2.
    fetcher = fake_fetcher([NO_TREE, TERMS, GLOSSARY])

    result = product_filter(fetcher, "pacote almofadinha")

    assert terms_of(result) == ["ALMOFADA", "PACOTE"]


def test_glossary_row_outside_the_list_is_ignored(fake_fetcher) -> None:
    fetcher = fake_fetcher([NO_TREE, TERMS, GLOSSARY])

    assert product_filter(fetcher, "leite sol") is None


def test_ambiguous_synonym_is_not_guessed(fake_fetcher) -> None:
    glossary = [*GLOSSARY, {"termo": "fardo", "sinonimos": "bolsa"}]
    fetcher = fake_fetcher([NO_TREE, TERMS, glossary])

    assert product_filter(fetcher, "bolsa") is None


def test_unknown_word_still_becomes_clarification(fake_fetcher) -> None:
    fetcher = fake_fetcher([NO_TREE, TERMS, GLOSSARY])

    assert product_filter(fetcher, "bolsa xpto") is None


def test_stopwords_alone_are_not_a_filter(fake_fetcher) -> None:
    assert product_filter(fake_fetcher([NO_TREE, TERMS]), "de") is None
