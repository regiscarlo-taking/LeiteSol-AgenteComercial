from leitesol_agent.application.operations.common import client_filter, group_filter, padded


def test_short_numeric_codes_also_try_the_padded_form() -> None:
    assert padded("534", 6) == ["534", "000534"]
    assert padded("000534", 6) == ["000534"]
    assert padded("VIPAO", 6) == ["VIPAO"]


def test_client_code_as_typed_finds_the_padded_registration() -> None:
    clause, params = client_filter("17351")
    assert "c.ClienteCodigo IN (?, ?)" in clause
    assert "017351" in params
    # O grupo de venda também é tentado com 6 posições.
    assert "c.Rede IN (?, ?)" in clause
    assert "017351" in params


def test_seven_digit_client_and_store_gets_the_leading_zero() -> None:
    clause, params = client_filter("1735101")
    assert "c.ClienteId IN (?, ?)" in clause
    assert "01735101" in params


def test_eight_digits_is_cnpj_root_or_client_and_store() -> None:
    clause, params = client_filter("01735101")
    assert clause == "(c.CNPJRaiz = ? OR c.ClienteId = ?)"
    assert params == ["01735101", "01735101"]


def test_full_cnpj_still_matches_the_cnpj() -> None:
    clause, params = client_filter("10.670.138/0002-32")
    assert params == ["10670138000232"]
    assert "c.CNPJ" in clause


def test_group_name_is_still_matched_by_description() -> None:
    clause, params = client_filter("vipao")
    assert params[-1] == "VIPAO"
    assert "GrupoVendaDescricao" in clause


def test_group_code_typed_without_zeros() -> None:
    clause, params = group_filter("534")
    assert clause == "(c.Rede IN (?, ?) OR c.GrupoVendaCodigo IN (?, ?))"
    assert params == ["534", "000534", "534", "000534"]
