from challenge.pii import mask_pii


def test_mascara_dados_pessoais():
    out = mask_pii("CPF 123.456.789-09, email a.b@x.com.br, tel (11) 98888-7777")
    assert "123.456" not in out and "@" not in out and "98888" not in out
    assert "[CPF]" in out and "[EMAIL]" in out and "[TELEFONE]" in out


def test_protocolo_nao_e_mascarado():
    assert mask_pii("REC-2026-00169") == "REC-2026-00169"
