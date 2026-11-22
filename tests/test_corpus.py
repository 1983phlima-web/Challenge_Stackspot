"""Qualidade do corpus: 500 textos distintos, coerentes com produto, canal, status e tom."""

import re
from collections import Counter

import pytest

from challenge.text import normalize
from corpus import PRODUCTS, generate_scenarios

THREAT = re.compile(
    r"procon|advogad|judicial|justica|ministerio publico|processar|danos morais|banco central|redes sociais"
)
HARD_THREAT = re.compile(
    r"procon|advogad|judicial|justica|ministerio publico|processar|danos morais"
)
PRAISE = re.compile(r"\b(elogio|agradec|parabens|satisfeit|obrigad|recomendo|feliz)")
PII = re.compile(r"\d{3}\.\d{3}\.\d{3}-\d{2}|@exemplo\.com\.br|\(11\) 9\d{4}-\d{4}")


@pytest.fixture(scope="module")
def scenarios():
    return generate_scenarios(500)


def test_quinhentos_textos_distintos_e_deterministicos(scenarios):
    assert len({s.text for s in scenarios}) == 500
    assert len({normalize(s.text) for s in scenarios}) == 500  # distintos também sem caixa/acento
    assert [s.text for s in generate_scenarios(500)] == [s.text for s in scenarios]


def test_cobertura_de_classes(scenarios):
    kinds = Counter(s.tension for s in scenarios)
    assert all(100 <= kinds[k] <= 220 for k in "AMB"), kinds
    assert 0.20 <= kinds["A"] / 500 <= 0.32
    assert {s.produto_code for s in scenarios} == {"EMP", "INV", "CAR", "CON", "SEG", "SEM"}
    assert {s.canal for s in scenarios} == set("BORSZ")
    assert {s.status for s in scenarios} == set("123")
    por_produto = Counter(s.produto for s in scenarios)
    assert set(por_produto) == set(PRODUCTS) and min(por_produto.values()) >= 20


def test_texto_corresponde_ao_produto(scenarios):
    for s in scenarios:
        text = normalize(s.text)
        own = [normalize(f) for f in PRODUCTS[s.produto][1][s.kind]]
        assert any(f in text for f in own), s.cenario
        others = [
            normalize(f)
            for name, (_, facts) in PRODUCTS.items()
            if name != s.produto
            for f in facts[s.kind]
        ]
        assert not any(f in text for f in others), s.cenario


def test_tom_coerente_com_tensao(scenarios):
    for s in scenarios:
        text = normalize(s.text)
        if s.kind == "A":
            assert THREAT.search(text), s.text
        else:
            assert not HARD_THREAT.search(text), s.text
        if s.kind == "Bp":
            assert PRAISE.search(text), s.text
        if s.kind == "M":
            assert not PRAISE.search(text), s.text


def test_contexto_do_canal(scenarios):
    for s in scenarios:
        text = normalize(s.text)
        if s.canal == "B":
            assert "banco central" in text, s.text
        if s.canal == "R":
            assert re.search(r"redes sociais|post", text), s.text
    assert not [s for s in scenarios if s.canal == "B" and s.tension == "B"]


def test_status_resolvida_combina_com_tom(scenarios):
    resolvidas = [s for s in scenarios if s.status == "3"]
    assert resolvidas and sum(s.kind == "Bp" for s in resolvidas) / len(resolvidas) > 0.4
    assert sum(s.kind == "A" for s in resolvidas) / len(resolvidas) < 0.1


def test_ha_textos_com_dados_pessoais_e_variacoes_de_estilo(scenarios):
    assert sum(bool(PII.search(s.text)) for s in scenarios) >= 10
    assert any(s.text.isupper() for s in scenarios)  # caixa alta (raiva)
    assert any(
        normalize(s.text) == s.text.casefold() and "ã" not in s.text and "ç" not in s.text
        for s in scenarios
    )
