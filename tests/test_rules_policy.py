import pytest

from challenge.domain.codes import FilaCode, Tension
from challenge.rules.engine import RulesEngine, RulesError
from challenge.rules.policy import PolicyBook, PolicyError


def test_regras_piso_e_limiares():
    eng = RulesEngine.from_text("@limiar_alta=3\nALTA;procon;3;s\nMEDIA;demora;1\nMEDIA;juros;1")
    ev = eng.evaluate("Vou ao PROCON!")
    assert ev.suggested is Tension.ALTA and ev.floor is Tension.ALTA
    assert eng.evaluate("demora e juros").suggested is Tension.MEDIA
    assert eng.evaluate("tudo certo").suggested is Tension.BAIXA


def test_curinga_e_palavra_inteira():
    eng = RulesEngine.from_text("ALTA;desesper*;3")
    assert eng.evaluate("Estou desesperado").matches
    assert not RulesEngine.from_text("ALTA;juro;3").evaluate("juros").matches


def test_regras_invalidas():
    with pytest.raises(RulesError):
        RulesEngine.from_text("XPTO;termo")


def test_politica_recuperacao_com_filtros():
    book = PolicyBook.from_text(
        "[P1]\nproduto: Empréstimo\npalavras: juros, contrato\nresposta: R1 {id}\n"
        "[P2]\nproduto: Seguros\npalavras: juros\nresposta: R2\n"
    )
    fila = FilaCode.parse("OEMP1A")
    found = book.find_candidates("cobrando juros fora do contrato", fila)
    assert [m.policy.id for m in found] == ["P1"]
    assert found[0].policy.render("REC-1", "Empréstimo") == "R1 REC-1"


def test_politica_duplicada():
    with pytest.raises(PolicyError):
        PolicyBook.from_text("[A]\npalavras: x\nresposta: y\n[a]\npalavras: x\nresposta: y\n")
