"""Corpus sintético de reclamações bancárias (pt-BR) com rótulo de tensão por construção.

Cada texto é composto por: abertura (tom) + frase de canal + fato do produto + frase de status
+ dado pessoal opcional + fechamento. O tom define a tensão esperada:

* ``A`` (Alta)  : ameaça (Procon, Justiça, advogado, Banco Central, exposição pública) e/ou desespero;
* ``M`` (Média) : insatisfação e cobrança de solução, sem ameaça;
* ``Bq`` (Baixa, dúvida) e ``Bp`` (Baixa, elogio): perguntas e clientes satisfeitos.

Os fatos são específicos de cada produto, de modo que o contexto do texto sempre corresponde à classe
de produto da linha. O corpus é sintético: serve para validar o fluxo e medir regressão, não substitui
uma amostra real rotulada por humanos.
"""

from __future__ import annotations

import random
import unicodedata
from dataclasses import dataclass

# nome no CSV -> (código de produto, fatos por tipo de tom)
PRODUCTS: dict[str, tuple[str, dict[str, list[str]]]] = {
    "Empréstimo": (
        "EMP",
        {
            "A": [
                "Meu empréstimo consignado teve parcelas descontadas em duplicidade e o banco se recusa a estornar.",
                "Estão me cobrando juros muito acima do que está no contrato do meu empréstimo pessoal.",
                "Quitei o empréstimo há meses e o banco continua descontando parcelas da minha conta.",
                "Contrataram um empréstimo em meu nome, sem autorização, e já estou sendo cobrado.",
            ],
            "M": [
                "A liberação do meu empréstimo está atrasada e o prazo informado já venceu.",
                "O valor da parcela do empréstimo veio diferente da simulação que me apresentaram.",
                "Pedi o boleto de quitação antecipada e até agora não recebi.",
                "Solicitei a revisão do contrato do empréstimo e não tive nenhuma posição.",
            ],
            "Bq": [
                "Como faço para antecipar parcelas do meu empréstimo e obter desconto nos juros?",
                "Qual é o prazo para o crédito do empréstimo cair na conta depois da aprovação?",
                "Posso renegociar as parcelas do meu empréstimo sem pagar multa?",
            ],
            "Bp": [
                "O gerente explicou com clareza as condições do empréstimo e liberou o valor no mesmo dia.",
                "A renegociação da minha dívida foi rápida e as parcelas ficaram dentro do meu orçamento.",
            ],
        },
    ),
    "Investimentos": (
        "INV",
        {
            "A": [
                "Meu resgate foi bloqueado e o dinheiro que preciso para pagar um tratamento médico não aparece na conta.",
                "Fui induzido a aplicar em um fundo de risco que não era o meu perfil e perdi boa parte da reserva.",
                "Há uma aplicação feita em meu nome que eu nunca autorizei, isso é fraude.",
                "A rentabilidade do meu CDB foi muito inferior à contratada e ninguém explica a diferença.",
            ],
            "M": [
                "O resgate da minha aplicação está demorando mais que o prazo informado no aplicativo.",
                "A taxa de administração do fundo foi cobrada em valor diferente do combinado.",
                "O extrato mostra uma rentabilidade diferente da que me foi apresentada na contratação.",
                "Não consigo visualizar minha carteira de investimentos no aplicativo há dias.",
            ],
            "Bq": [
                "Qual é a diferença entre CDB e LCI e qual rende mais para um prazo de dois anos?",
                "Como funciona a cobrança de imposto de renda sobre os rendimentos dos meus investimentos?",
                "Em quantos dias úteis o resgate de um fundo de renda fixa cai na conta?",
            ],
            "Bp": [
                "A assessora de investimentos montou uma carteira adequada ao meu perfil e acompanha tudo com atenção.",
                "O resgate que pedi caiu na conta no mesmo dia, sem burocracia.",
            ],
        },
    ),
    "Cartão de Crédito": (
        "CAR",
        {
            "A": [
                "Meu cartão foi clonado, fizeram compras que não reconheço e o banco insiste em me cobrar a fatura.",
                "Fui cobrado em duplicidade na fatura do cartão e o banco se recusa a estornar.",
                "Meu cartão foi bloqueado por engano durante uma viagem e fiquei sem como pagar a hospedagem.",
                "Cancelaram meu cartão de crédito sem aviso e negativaram meu nome indevidamente.",
            ],
            "M": [
                "O limite do meu cartão foi reduzido sem aviso prévio.",
                "A anuidade do cartão veio cobrada mesmo após o cancelamento do serviço.",
                "A fatura chegou com um encargo que não consigo identificar.",
                "O novo cartão que solicitei não chegou e o prazo de entrega já passou.",
            ],
            "Bq": [
                "Como faço para aumentar o limite do meu cartão de crédito?",
                "Qual é a data de vencimento mais próxima que posso escolher para a fatura?",
                "Posso parcelar a fatura do cartão em quantas vezes e com qual taxa?",
            ],
            "Bp": [
                "A atendente resolveu a contestação de uma compra no meu cartão em poucos minutos.",
                "O programa de pontos do cartão funcionou perfeitamente e troquei por passagens sem complicação.",
            ],
        },
    ),
    "Conta Corrente": (
        "CON",
        {
            "A": [
                "Minha conta corrente foi bloqueada sem justificativa e estou sem acesso ao meu salário.",
                "Fizeram transferências por Pix da minha conta que eu não autorizei, foi um golpe e o banco não devolve.",
                "Descontaram tarifas indevidas na minha conta por meses e se recusam a devolver o valor.",
                "Encerraram minha conta sem aviso e meu dinheiro ficou retido.",
            ],
            "M": [
                "Cobraram uma tarifa de pacote de serviços que eu não contratei.",
                "O Pix que fiz há dois dias ainda não foi creditado para o destinatário.",
                "O aplicativo da conta corrente trava toda vez que tento pagar um boleto.",
                "Pedi a segunda via do extrato e o documento veio com informações erradas.",
            ],
            "Bq": [
                "Como altero o limite diário de transferências por Pix da minha conta?",
                "Quais são as tarifas do pacote de serviços da conta corrente?",
                "Como faço para cadastrar uma nova chave Pix no aplicativo?",
            ],
            "Bp": [
                "O gerente da minha agência resolveu um problema com a conta de forma rápida e educada.",
                "O novo aplicativo ficou muito mais simples de usar e já consigo fazer tudo pelo celular.",
            ],
        },
    ),
    "Seguros": (
        "SEG",
        {
            "A": [
                "Meu seguro de vida foi negado após o sinistro, mesmo com toda a documentação entregue.",
                "Cobraram um seguro que eu nunca contratei e já descontaram várias parcelas da minha conta.",
                "O seguro do meu carro não cobriu a colisão e estou sem veículo e sem indenização.",
                "Cancelei o seguro e continuam cobrando a apólice, o valor já passa de mil reais.",
            ],
            "M": [
                "O prazo para análise do meu sinistro já passou e ninguém retornou.",
                "A apólice enviada contém dados incorretos sobre os beneficiários.",
                "O reajuste do meu seguro residencial veio muito acima do que foi informado.",
                "Tenho dificuldade para acionar a assistência 24 horas do seguro.",
            ],
            "Bq": [
                "Como faço para incluir um novo beneficiário na minha apólice de seguro de vida?",
                "O seguro residencial cobre danos causados por chuva?",
                "Qual é o procedimento para renovar a apólice do seguro do meu carro?",
            ],
            "Bp": [
                "O sinistro do meu carro foi liberado em dois dias e o atendimento foi excelente.",
                "A corretora esclareceu todas as coberturas do seguro com muita paciência.",
            ],
        },
    ),
    "Consórcio": (
        "SEM",
        {
            "A": [
                "Fui contemplado no consórcio e o banco não libera a carta de crédito, mesmo com tudo pago em dia.",
                "Estão cobrando taxas extras no meu consórcio que não estavam no contrato.",
                "Cancelaram minha cota de consórcio por engano e não devolvem o que paguei.",
                "Paguei a entrada do consórcio e o grupo foi encerrado sem que eu fosse avisado.",
            ],
            "M": [
                "A assembleia do consórcio foi remarcada duas vezes sem aviso.",
                "O boleto do consórcio veio com valor diferente do informado.",
                "A carta de crédito está demorando para ser liberada após a contemplação.",
                "Não recebi o extrato atualizado do meu grupo de consórcio.",
            ],
            "Bq": [
                "Como funciona o lance embutido no consórcio?",
                "Posso usar a carta de crédito do consórcio para comprar um imóvel usado?",
                "Qual o prazo para pagamento após a contemplação do consórcio?",
            ],
            "Bp": [
                "Fui contemplado e a equipe do consórcio conduziu todo o processo com muita transparência.",
                "O atendimento para o meu lance no consórcio foi ágil e educado.",
            ],
        },
    ),
    "Financiamento Imobiliário": (
        "SEM",
        {
            "A": [
                "O financiamento do meu imóvel foi negado na véspera da assinatura e já perdi o sinal dado ao vendedor.",
                "Estão cobrando parcelas do financiamento com juros acima do contrato e corrigidas de forma abusiva.",
                "Quitei o financiamento imobiliário e o banco não libera a baixa da hipoteca, travando a venda da casa.",
                "Cobraram o seguro habitacional em dobro e se recusam a estornar.",
            ],
            "M": [
                "A avaliação do imóvel para o financiamento está demorando mais do que o prazo informado.",
                "A simulação do financiamento mostrou parcela menor do que a apresentada no contrato.",
                "Solicitei a amortização extraordinária e até hoje não tenho confirmação.",
                "A documentação do financiamento foi pedida de novo, mesmo tendo sido entregue.",
            ],
            "Bq": [
                "Posso usar o FGTS para amortizar o financiamento do meu imóvel?",
                "Como faço para simular a portabilidade do financiamento imobiliário para outro banco?",
                "Quais documentos preciso para solicitar o financiamento de um apartamento?",
            ],
            "Bp": [
                "O analista de crédito acompanhou meu financiamento imobiliário do início ao fim e cumpriu todos os prazos.",
                "A aprovação do financiamento da casa própria saiu antes do previsto.",
            ],
        },
    ),
    "Previdência Privada": (
        "SEM",
        {
            "A": [
                "Pedi o resgate da minha previdência privada e o banco retém o valor há meses, sem explicação.",
                "Descontaram contribuições de previdência que eu nunca contratei, é fraude.",
                "O saldo da minha previdência privada caiu de forma absurda e ninguém explica o motivo.",
                "Fui induzido a migrar de plano de previdência e perdi benefícios a que tinha direito.",
            ],
            "M": [
                "O extrato da previdência privada não está sendo atualizado no aplicativo.",
                "A taxa de carregamento foi cobrada em valor diferente do combinado.",
                "Solicitei a alteração do valor da contribuição e até agora não foi feita.",
                "O informe de rendimentos da previdência chegou com valores incorretos.",
            ],
            "Bq": [
                "Qual a diferença entre PGBL e VGBL para o meu imposto de renda?",
                "Como altero a data do débito da contribuição da previdência?",
                "Posso portar minha previdência privada para outra instituição?",
            ],
            "Bp": [
                "A consultora de previdência explicou o plano com clareza e me ajudou a planejar a aposentadoria.",
                "O resgate parcial da previdência foi concluído em poucos dias, tudo muito tranquilo.",
            ],
        },
    ),
    "Câmbio": (
        "SEM",
        {
            "A": [
                "Minha remessa internacional não chegou ao destino e o banco retém o dinheiro há semanas, estou sem recursos no exterior.",
                "Cobraram uma cotação do dólar muito acima da combinada na compra de moeda e se recusam a corrigir.",
                "Meu cartão pré-pago de viagem foi bloqueado no exterior e fiquei sem dinheiro.",
                "Fizeram um câmbio que eu não autorizei e debitaram um valor alto da minha conta.",
            ],
            "M": [
                "A compra de moeda estrangeira está demorando para ser entregue na agência.",
                "A taxa de câmbio aplicada foi diferente da que o gerente informou por telefone.",
                "Solicitei o comprovante da remessa internacional e ainda não recebi.",
                "O recibo da compra de dólares veio com dados incorretos.",
            ],
            "Bq": [
                "Como faço para comprar dólares para uma viagem e retirar na agência?",
                "Qual o prazo médio para uma remessa internacional ser creditada?",
                "Existe limite para recarga do cartão pré-pago de viagem?",
            ],
            "Bp": [
                "A compra de euros foi rápida e a cotação ficou melhor do que a de outras casas.",
                "O atendimento no câmbio foi muito cordial e a retirada da moeda foi sem filas.",
            ],
        },
    ),
}
PRODUCT_WEIGHTS = {"Empréstimo": 16, "Investimentos": 12, "Cartão de Crédito": 20, "Conta Corrente": 18,
                   "Seguros": 10, "Consórcio": 6, "Financiamento Imobiliário": 6,
                   "Previdência Privada": 6, "Câmbio": 6}  # fmt: skip

OPENERS = {
    "A": ["Estou desesperado, não sei mais a quem recorrer.",
          "Isso é um absurdo e uma falta de respeito com o cliente.",
          "Estou indignada e já perdi a paciência com esse banco.",
          "Sou cliente há mais de dez anos e nunca fui tão maltratado.",
          "Estou sendo lesado e ninguém assume a responsabilidade.",
          "Chega de descaso, minha situação financeira está comprometida por culpa de vocês.",
          "Estou passando necessidade por causa dessa falha do banco.",
          "Isso é inaceitável."],
    "M": ["Estou insatisfeito com o atendimento que recebi.",
          "Já entrei em contato mais de uma vez e continuo sem resposta.",
          "Fico chateada com a demora para resolverem isso.",
          "Gostaria de registrar meu descontentamento.",
          "O prazo que me passaram já foi ultrapassado.",
          "Não estou conseguindo resolver isso pelos canais comuns."],
    "Bq": ["Olá, tudo bem?", "Bom dia!", "Boa tarde.", "Prezados, uma dúvida:"],
    "Bp": ["Quero registrar um elogio.", "Escrevo para agradecer o atendimento.",
           "Fiquei muito satisfeito e precisava compartilhar.", "Parabéns ao banco pelo serviço!"],
}  # fmt: skip
CLOSERS = {
    "A": ["Se não resolverem hoje, vou ao Procon.",
          "Já estou com meu advogado preparando uma ação judicial.",
          "Vou denunciar ao Banco Central e expor o caso nas redes sociais.",
          "Isso vai parar na Justiça se não houver solução imediata.",
          "Exijo solução imediata, ou levo o caso ao Ministério Público.",
          "Se não corrigirem em 48 horas, vou processar o banco por danos morais."],
    "M": ["Peço que verifiquem e me deem um retorno ainda esta semana.",
          "Aguardo uma posição do banco.",
          "Preciso de uma solução rápida, por favor.",
          "Espero que analisem com mais atenção.",
          'Me prometeram "retorno em 24 horas" e até hoje nada.'],
    "Bq": ["Agradeço desde já.", "Obrigado pela atenção.", "Fico no aguardo, sem pressa.", "Desde já, muito obrigada."],
    "Bp": ["Parabéns à equipe, continuem assim!", "Recomendo o banco aos meus amigos.",
           "Sigo muito feliz com o atendimento.", "Obrigada por tudo!"],
}  # fmt: skip
CHANNEL_SENTENCES = {
    "O": {"A": "Já abri protocolo no SAC, não resolveram e agora recorro à ouvidoria.",
          "M": "Estou na ouvidoria porque o SAC não resolveu meu caso.",
          "Bq": "Procuro a ouvidoria para deixar meu registro.",
          "Bp": "Registro na ouvidoria meu agradecimento."},
    "S": {"A": "Liguei para o SAC várias vezes e fui tratado com descaso.",
          "M": "Liguei no SAC e a ligação caiu duas vezes.",
          "Bq": "Tentei o SAC, mas a fila estava grande e prefiro escrever.",
          "Bp": "Falei com o SAC e fui muito bem atendida."},
    "R": {"A": "Vou publicar este caso nas redes sociais e marcar o banco.",
          "M": "Estou postando aqui porque pelo aplicativo ninguém responde.",
          "Bq": "Posto aqui porque vi que vocês respondem rápido.",
          "Bp": "Estou postando aqui para agradecer publicamente."},
    "B": {"A": "Já registrei este caso no Banco Central.",
          "M": "Registro aqui no Banco Central porque o banco não respondeu ao meu pedido.",
          "Bq": "Registro neste canal do Banco Central apenas para pedir uma orientação.",
          "Bp": "Registro neste canal do Banco Central um elogio ao atendimento recebido."},
    "Z": {},
}  # fmt: skip
CHANNEL_PROB = {"B": 1.0, "R": 1.0, "O": 0.5, "S": 0.5, "Z": 0.0}
STATUS_SENTENCES = {
    ("A", "1"): ["Até agora ninguém me deu retorno.", "O problema continua sem solução.",
                 "Já se passaram semanas e nada foi resolvido."],
    ("A", "2"): ["Disseram que o caso está em análise, mas nada acontece.",
                 "Me informaram que estão analisando, só que o prazo não é cumprido."],
    ("A", "3"): ["Mesmo com o chamado encerrado, o problema voltou a acontecer."],
    ("M", "1"): ["Até agora ninguém me deu retorno.", "O problema continua sem solução."],
    ("M", "2"): ["O chamado está em análise há dias e ninguém me atualiza.",
                 "Disseram que estão analisando, mas o prazo passou."],
    ("M", "3"): ["Deram o caso como resolvido, mas na prática nada mudou."],
    ("Bq", "1"): ["Não tenho urgência."], ("Bq", "2"): ["Vou acompanhar a análise por aqui."],
    ("Bq", "3"): ["Já resolvi o principal, resta só essa dúvida."],
    ("Bp", "1"): ["Estou acompanhando e tudo caminha bem."],
    ("Bp", "2"): ["Pelo que vi, a análise está andando muito bem."],
    ("Bp", "3"): ["Meu caso foi resolvido rapidamente.", "O problema foi solucionado dentro do prazo."],
}  # fmt: skip
PII_SENTENCES = [
    "Meu CPF é {cpf}.",
    "Pode me retornar pelo e-mail {email}.",
    "Meu telefone é {phone}.",
]

KIND_WEIGHTS = {"A": 24, "M": 36, "Bq": 24, "Bp": 16}
CHANNEL_WEIGHTS = {
    "A": {"O": 30, "S": 15, "R": 20, "B": 20, "Z": 15},
    "M": {"O": 25, "S": 35, "R": 10, "B": 10, "Z": 20},
    "Bq": {"O": 10, "S": 40, "R": 10, "B": 0, "Z": 40},
    "Bp": {"O": 20, "S": 40, "R": 25, "B": 0, "Z": 15},
}
STATUS_WEIGHTS = {
    "A": {"1": 60, "2": 37, "3": 3},
    "M": {"1": 50, "2": 40, "3": 10},
    "Bq": {"1": 50, "2": 20, "3": 30},
    "Bp": {"1": 10, "2": 15, "3": 75},
}
TENSION_OF_KIND = {"A": "A", "M": "M", "Bq": "B", "Bp": "B"}


@dataclass(frozen=True)
class Scenario:
    """Texto gerado e seu contexto (rótulos esperados)."""

    produto: str  # nome no CSV
    produto_code: str
    kind: str  # A | M | Bq | Bp
    canal: str  # B | O | R | S | Z
    status: str  # 1 | 2 | 3
    text: str

    @property
    def tension(self) -> str:
        """Letra de tensão esperada (A/M/B)."""
        return TENSION_OF_KIND[self.kind]

    @property
    def cenario(self) -> str:
        """Descrição curta para o gabarito."""
        return f"{self.produto}|{self.kind}|{self.canal}|{self.status}"


def _wchoice(rng: random.Random, weights: dict[str, int]) -> str:
    return rng.choices(list(weights), weights=list(weights.values()))[0]


def normalize(text: str) -> str:
    """Caixa e acentos removidos (mesma regra do cache do classificador)."""
    return " ".join(_strip_accents(text).casefold().split())


def _strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _pii(rng: random.Random) -> str:
    cpf = f"{rng.randint(100, 999)}.{rng.randint(100, 999)}.{rng.randint(100, 999)}-{rng.randint(10, 99)}"
    email = f"cliente{rng.randint(100, 999)}@exemplo.com.br"
    phone = f"(11) 9{rng.randint(1000, 9999)}-{rng.randint(1000, 9999)}"
    return rng.choice(PII_SENTENCES).format(cpf=cpf, email=email, phone=phone)


def make_scenario(rng: random.Random) -> Scenario:
    """Sorteia um contexto coerente e compõe o texto."""
    kind = _wchoice(rng, KIND_WEIGHTS)
    produto = _wchoice(rng, PRODUCT_WEIGHTS)
    code, facts = PRODUCTS[produto]
    canal = _wchoice(rng, CHANNEL_WEIGHTS[kind])
    status = _wchoice(rng, STATUS_WEIGHTS[kind])
    parts = [rng.choice(OPENERS[kind])]
    channel_sentence = CHANNEL_SENTENCES[canal].get(kind)
    if channel_sentence and rng.random() < CHANNEL_PROB[canal]:
        parts.append(channel_sentence)
    parts.append(rng.choice(facts[kind]))
    if rng.random() < 0.7:
        parts.append(rng.choice(STATUS_SENTENCES[(kind, status)]))
    if kind in {"A", "M"} and rng.random() < 0.08:
        parts.append(_pii(rng))
    parts.append(rng.choice(CLOSERS[kind]))
    text = " ".join(parts)
    style = rng.random()
    if style < 0.06:
        text = _strip_accents(text)
    elif style < 0.14 and kind == "A":
        text = text.upper()
    return Scenario(produto, code, kind, canal, status, text)


def generate_scenarios(n: int, seed: int = 2026) -> list[Scenario]:
    """Gera ``n`` cenários com textos distintos, inclusive após normalizar caixa e acentos."""
    rng = random.Random(seed)
    seen: set[str] = set()
    out: list[Scenario] = []
    while len(out) < n:
        scenario = make_scenario(rng)
        key = normalize(scenario.text)
        if key not in seen:
            seen.add(key)
            out.append(scenario)
    return out
