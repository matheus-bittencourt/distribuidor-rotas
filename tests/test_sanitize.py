from app.sanitize import clean_value, is_sensitive_header, mask_text


def test_masks_cpf_cnpj_valor_telefone():
    txt = "João CPF 123.456.789-09 deve R$ 1.234,56 tel (51) 99876-5432 email a@b.com 12.345.678/0001-90"
    out, counts = mask_text(txt)
    for secret in ("123.456.789-09", "1.234,56", "99876-5432", "a@b.com", "12.345.678/0001-90"):
        assert secret not in out
    assert {"cpf", "valor", "telefone", "email", "cnpj"} <= set(counts)


def test_keeps_address_and_cep():
    out, _ = mask_text("Rua dos Andradas, 1234 - Centro Histórico - CEP 90020-007 - apto 502")
    assert "1234" in out and "90020-007" in out and "apto 502" in out


def test_unformatted_cpf_and_long_numbers():
    out, _ = mask_text("12345678909 contrato 20240001234567")
    assert "12345678909" not in out and "20240001234567" not in out


def test_headers():
    assert is_sensitive_header("CPF") and is_sensitive_header("Valor da dívida")
    assert is_sensitive_header("Telefone") and is_sensitive_header("Nome da mãe")
    assert not is_sensitive_header("Nome") and not is_sensitive_header("Endereço")
    assert not is_sensitive_header("Número") and not is_sensitive_header("Bairro")


def test_clean_value_drops_marker():
    assert clean_value("Maria 123.456.789-09") == "Maria"
