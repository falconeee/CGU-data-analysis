from cgu import cnpj


def test_valid_numeric():
    assert cnpj.is_valid("32.479.123/0001-43")
    assert not cnpj.is_valid("32.479.123/0001-44")


def test_valid_alphanumeric_official_example():
    # Exemplo publicado pela Receita para o CNPJ alfanumérico
    assert cnpj.normalize("12.ABC.345/01DE-35") == "12ABC34501DE35"
    assert cnpj.is_valid("12.ABC.345/01DE-35")
    assert not cnpj.is_valid("12.ABC.345/01DE-36")


def test_lowercase_and_lost_leading_zeros():
    assert cnpj.normalize("12abc34501de35") == "12ABC34501DE35"
    assert cnpj.normalize(2479123000143) == "02479123000143"


def test_cpf_is_not_cnpj():
    assert cnpj.normalize("186.181.461-53") is None
    assert cnpj.normalize("***.181.461-**") is None


def test_make_and_format_roundtrip():
    value = cnpj.make("Z1A2B3C4")
    assert cnpj.is_valid(value)
    assert cnpj.base(value) == "Z1A2B3C4"
    assert cnpj.fmt(value) == f"Z1.A2B.3C4/0001-{value[-2:]}"
