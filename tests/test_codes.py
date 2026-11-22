import pytest

from challenge.domain.codes import FilaCode, Tension, canal_code, produto_code, status_code


@pytest.mark.parametrize(
    ("canal", "produto", "status", "tensao", "esperado"),
    [
        ("Banco Central", "Empréstimo", "Resolvida", Tension.ALTA, "BEMP3A"),
        ("Ouvidoria", "Cartão de Crédito", "Em análise", Tension.MEDIA, "OCAR2M"),
        ("Chat", "Consórcio", "Aberta", Tension.BAIXA, "ZSEM1B"),
    ],
)
def test_exemplos_do_enunciado(canal, produto, status, tensao, esperado):
    code = FilaCode(canal_code(canal), produto_code(produto), status_code(status), tensao)
    assert str(code) == esperado
    assert FilaCode.parse(esperado) == code


def test_normalizacao_tolerante():
    assert canal_code("  OUVIDORIA ") == "O"
    assert produto_code("emprestimo") == "EMP"
    assert status_code("EM ANALISE") == "2"
    assert status_code("Cancelada") is None


def test_parse_invalido():
    with pytest.raises(ValueError, match="inválido"):
        FilaCode.parse("XXXX")
