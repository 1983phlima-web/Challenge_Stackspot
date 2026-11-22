# SPEC — Challenge Automation (Triagem de Reclamações com IA)

Versão 2.0 · Provedor de IA neste pacote: **StackSpot AI** · Escopo: Processo 1 (Pré-processamento) e Processo 2 (Performer com ciclo `_loop`)

## 1. Objetivo
Automatizar a triagem de reclamações recebidas em `C:\Challenge\dataset_challenge.csv`: classificar a **tensão** de cada texto com IA apoiada por um Motor de Regras, montar o **código de fila**, ordenar a fila de trabalho e, em um segundo processo, recomendar a **resposta** (política aprovada quando existir). Itens sem resposta entram em um **ciclo de reprocessamento** (`_loop`). Tudo com log analítico/estatístico e relatório gerencial.

## 2. Premissas e pontos em aberto (validar com o negócio)
| # | Premissa adotada | Impacto se diferente |
|---|---|---|
| P1 | O CSV tem **6 colunas** (`id,data_reclamacao,canal,texto_reclamacao,produto,status`). | Ajustar `REQUIRED_COLUMNS`. |
| P2 | `Fila\processadas_<ts>.csv` contém **todas** as linhas válidas (inclusive Resolvidas), pois o código exige a classe de status 3. | — |
| P3 | O `_read` e os demais estados ficam em `Output\`; o Performer varre essa pasta. | Mudar `output_subdir`. |
| P4 | "Canais do maior para o menor volume" usa a contagem **na própria fila** (sem Resolvidas). Empate: B, O, R, S, Z. | — |
| P5 | Dentro do canal: Tensão (Alta>Média>Baixa) → Status (Aberta>Em análise) → data mais antiga → id. | — |
| P6 | Canal/produto desconhecidos viram `Z`/`SEM`; **status desconhecido é rejeitado** (não existe classe). | — |
| P7 | Formatos dos TXT (Motor de Regras e Política) são os da §5.3–5.4; o parser é isolado (`rules/`). | Trocar apenas os parsers. |
| P8 | "Arquivo `_nok` vira `_loop`": falha **por linha** gera `_loop` (pendentes) e `_ok` (respondidas). `_nok` permanece para (a) erro de arquivo e (b) ciclos esgotados — casos que exigem análise humana. | — |
| P9 | "Segunda rodada" = retentativa dos pendentes na mesma execução (`loop_rounds_per_run=2`); o que restar espera a próxima execução, até `max_loop_cycles=5`. | Ajustar os parâmetros. |

## 3. Requisitos funcionais
- **RF-01** Ler `dataset_challenge.csv` (UTF-8 com/sem BOM; fallback CP1252) como texto, sem coerção de tipos.
- **RF-02** Validar linhas; rejeitar (quarentena em `Fila\rejeitadas_<ts>.csv`, com coluna `motivo`) id vazio/duplicado, data fora de `YYYY-MM-DD`, texto vazio, status inválido.
- **RF-03** Código de fila `<Canal><Produto><Status><Tensão>`: Canal B/O/R/S/Z; Produto EMP/INV/CAR/CON/SEG/SEM; Status 1/2/3; Tensão A/M/B (ex.: `BEMP3A`, `OCAR2M`, `ZSEM1B`).
- **RF-04** Classificar a tensão com IA, usando os termos do Motor de Regras como evidência; termos com *piso* impõem tensão mínima.
- **RF-05** Gravar `Fila\processadas_<timestamp>.csv` = estrutura original + coluna `fila`.
- **RF-06** Gerar `Output\processadas_<ts>_read.csv`: sem Resolvidas; canais por volume; depois tensão e status.
- **RF-07** Performer: para cada `*_read.csv` ou `*_loop.csv`, gerar `Resposta`: política aderente (texto verbatim) ou resposta recomendada pela IA.
- **RF-08** Linhas respondidas vão para `<base>_ok.csv` (acumulado, **na ordem original da fila**).
- **RF-09** Linhas sem resposta vão para `<base>_loop.csv` (mesma estrutura do `_read`, **sem** `Resposta`); o `_read` é removido.
- **RF-10** Na mesma execução, reprocessar somente os pendentes (`loop_rounds_per_run`); persistir o que restar para o próximo ciclo; ao atingir `max_loop_cycles`, mover os pendentes para `<base>_nok.csv`.
- **RF-11** Erro de arquivo (ilegível, colunas ausentes) → `<base>_nok.csv`, sem afetar os demais lotes.
- **RF-12** Log estruturado (JSON), trilha analítica por linha (JSONL), estatísticas (JSON) e relatório gerencial (MD+HTML) com **Resumo, Tendências e Top Riscos** por execução/rodada.

## 4. Requisitos não funcionais
| ID | Requisito | Como é atendido |
|---|---|---|
| RNF-01 | Qualidade | PEP 8/257/484/517/621; `ruff` e `mypy --strict` sem pendências; testes `pytest`. |
| RNF-02 | Resiliência | Retentativas com backoff+jitter (429/5xx/rede/JSON inválido); renovação de token em 401; fallback para regras na tensão; falha isolada por linha; ciclo `_loop`. |
| RNF-03 | Atomicidade | `.tmp` + `os.replace`; ordem segura: grava `_ok`, depois `_loop`, depois remove a origem (reexecução após queda é idempotente: `_ok` deduplica por `id`). |
| RNF-04 | Concorrência | `ThreadPoolExecutor` (`llm_workers`); lock por arquivo (`.lock`, `O_EXCL`). |
| RNF-05 | Custo/Latência | Cache por hash do texto; somente textos únicos vão à IA. |
| RNF-06 | Privacidade (LGPD) | Máscara de CPF/CNPJ/e-mail/cartão/telefone antes de enviar ao modelo; segredos só por variável de ambiente. |
| RNF-07 | Segurança de prompt | Texto da reclamação delimitado e tratado como dado; saída validada (política só dentre candidatas; tensão só Alta/Média/Baixa). |
| RNF-08 | Observabilidade | `run_id` e `ciclo` em log/auditoria; estatísticas por rodada (origem, falhas, latência média/p95). |
| RNF-09 | Determinismo | `temperature=0` (Ollama); desempate estável na ordenação. |
| RNF-10 | Portabilidade | Windows 10/11/Server; Python ≥ 3.11. |

## 5. Contratos de dados
### 5.1 Entrada
`id,data_reclamacao,canal,texto_reclamacao,produto,status` · separador `,` · aspas duplas em textos com vírgula · datas `YYYY-MM-DD`.

### 5.2 Artefatos
| Artefato | Local | Conteúdo |
|---|---|---|
| `processadas_<ts>.csv` | `Fila\` | original + `fila` (todas as linhas válidas) |
| `rejeitadas_<ts>.csv` | `Fila\` | linhas rejeitadas + `motivo` |
| `processadas_<ts>_read.csv` | `Output\` | fila ordenada, sem Resolvidas |
| `processadas_<ts>_ok.csv` | `Output\` | itens respondidos: `_read` + `Resposta` (acumulado entre ciclos) |
| `processadas_<ts>_loop.csv` | `Output\` | itens **sem** resposta, aguardando novo ciclo (sem `Resposta`) |
| `processadas_<ts>_nok.csv` | `Output\` | erro de arquivo ou ciclos esgotados (análise humana) |
| `processadas_<ts>.state.json` | `Output\` | `{"base","order":[ids],"cycles":n}`: ordem original e nº de ciclos |
| `audit_*.jsonl`, `stats_*.json`, `*.log` | `Logs\` | trilha analítica, estatísticas, log JSON rotativo |
| `relatorio_*.md/.html` | `Relatorios\` | Resumo, Tendências, Top Riscos |

### 5.3 Motor de Regras (TXT)
```
@limiar_alta=3        # soma de pesos ALTA que sugere Alta
@limiar_media=2       # soma ALTA+MEDIA que sugere Média
ALTA;procon;3;s       # nivel;termo;peso;piso(s/n) — '*' é curinga (desesper*)
```
Comparação sem acento/caixa, por palavra inteira. Nível final = `max(IA, piso)`; sem IA (ou na falha dela), usa-se o nível sugerido pelos limiares.

### 5.4 Política (TXT)
```
[POL-EMP-001]
produto: Empréstimo        # rótulo, código ou *
canal: *                   # opcional; filtro duro
tensao: *                  # opcional; filtro duro
palavras: juros, contrato, cobranca indevida
resposta: Texto aprovado. Protocolo {id}.   # placeholders: {id}, {produto}
```

### 5.5 Contratos JSON com o modelo
- Tensão → `{"tensao":"Alta|Média|Baixa","confianca":0-1,"justificativa":"..."}`
- Resposta → `{"politica_id":"ID"|null,"confianca":0-1,"justificativa":"...","resposta":"..."}`

### 5.6 Provedor de IA — StackSpot AI (Agents API)
- **Token:** `POST https://idm.stackspot.com/{realm}/oidc/oauth/token` (`grant_type=client_credentials`, `client_id`, `client_secret`); cache com margem de 60 s e renovação automática; HTTP 401 invalida o token e repete.
- **Inferência:** `POST https://genai-inference-app.stackspot.com/v1/agent/{agent_id}/chat` com `{"streaming":false,"user_prompt":"<sistema + usuário>","stackspot_knowledge":false,"return_ks_in_response":false}`; resposta em `message`.
- As configurações do **agente no portal** (LLM, instruções, Knowledge Sources) continuam valendo: use um agente **dedicado**, sem Knowledge Sources, para não contaminar a classificação. O JSON é exigido no próprio prompt.
- Credenciais: `STACKSPOT_CLIENT_ID` e `STACKSPOT_CLIENT_SECRET` (ambiente); `stackspot_realm` e `stackspot_agent_id` em `settings.yaml`. Dados são enviados à plataforma: mantenha `mask_pii: true` e valide o enquadramento LGPD/contratual.

## 6. Regras de negócio
### 6.1 Código de fila
Canal: Banco Central=B, Ouvidoria=O, Redes Sociais=R, SAC=S, outro=Z. Produto: Empréstimo=EMP, Investimentos=INV, Cartão de Crédito=CAR, Conta Corrente=CON, Seguros=SEG, outro=SEM. Status: Aberta=1, Em análise=2, Resolvida=3. Tensão: A/M/B. Comparação sem acento, caixa ou espaços extras.

### 6.2 Tensão
1. Motor de Regras avalia o texto → termos, nível sugerido, piso. 2. Com IA: envia texto mascarado + termos; valida o JSON; falha definitiva → `REGRAS_FALLBACK`. 3. `nivel = max(IA, piso)`; origem registrada: `IA`, `IA+PISO_REGRA`, `REGRAS`, `REGRAS_FALLBACK`.

### 6.3 Seleção da resposta
1. Até `policy_top_k` candidatas por filtros duros (produto/canal/tensão) + aderência lexical. 2. A IA escolhe **uma** somente se resolver o problema central; confiança < `min_policy_confidence` ou ID fora das candidatas → descartada. 3. Política escolhida → texto verbatim (`POLITICA`); senão resposta gerada (`IA_GERADA`, prefixo "[Sugestão IA - revisar]"). 4. IA indisponível: política com aderência ≥ `policy_lexical_threshold` (`POLITICA_LEXICAL`); senão a linha **falha** e vai para `_loop`.

### 6.4 Score de risco (relatório)
`score = (peso_tensão × peso_canal + envelhecimento) × peso_status` · tensão A/M/B = 3/2/1 · canal B/O/R/S/Z = 3/2/2/1/1 · status Aberta/Em análise = 1,5/1,0 · envelhecimento = min(dias/30, 5).

### 6.5 Máquina de estados do lote
```
(Processo 1)  .tmp ──rename atômico──▶ <base>_read.csv
<base>_read.csv ──rodada 1──▶ respondidas ▶ <base>_ok.csv
                          └─▶ pendentes   ▶ <base>_loop.csv   (+ state.json: cycles=1)
<base>_loop.csv ──rodada n (mesma execução ou próxima)──▶ respondidas ▶ acrescentadas a <base>_ok.csv
                                                     └─▶ pendentes  ▶ <base>_loop.csv  (cycles=n)
sem pendentes ─────────────▶ remove _loop/_read e state.json  (lote concluído)
pendentes e cycles ≥ max_loop_cycles ─▶ <base>_nok.csv (análise humana)
erro de arquivo ──────────────────────▶ <base>_nok.csv
```

## 7. Erros e códigos de saída
| Situação | Comportamento | Saída |
|---|---|---|
| Entrada ausente / schema / config inválidos | Mensagem + log; nada é gravado | 2 |
| IA indisponível no Processo 1 | Fallback para regras | 0 |
| Linhas sem resposta | `_ok` parcial + `_loop`; retentativa na mesma execução | 1 se restarem pendentes |
| Ciclos esgotados / erro de arquivo | `_nok` | 1 |
| Lock existente | Arquivo ignorado | 0 |
| Erro inesperado | Log com stack trace | 3 |
Saída `0` significa que todos os lotes foram concluídos (`_ok`).

## 8. Observabilidade
Log operacional (`preprocess.log`, `performer.log`; JSON, rotação 10 MB×10). Auditoria `audit_*.jsonl`: `row_rejected`, `row_classified`, `row_queued`, `row_answered`, `row_failed` (com `ciclo`). Estatísticas `stats_*.json`. Relatório: 1) Resumo · 2) Tendências (volume m/m, mix de tensão, variação por produto, cobertura de política) · 3) Top Riscos (itens, concentração canal×produto, termos; no Performer: Alta sem política e pendentes).

## 9. Segurança e conformidade
Máscara de PII antes da IA; CSV nunca alterado na origem; segredos fora do código e do YAML; defesa contra *prompt injection*; ACL restrita em `C:\Challenge`; retenção definida para `Logs\` (IDs e justificativas, sem o texto integral).

## 10. Estratégia de testes
- **Corpus de 500 textos distintos** (`tests/corpus.py`) de reclamações bancárias em pt-BR, gerado de forma determinística e **rotulado por construção** (tensão, produto, canal e status). Cada texto combina: abertura (tom) + frase de canal + fato específico do produto + frase de status + dado pessoal opcional + fechamento.
  - **Tensão:** Alta (ameaça de Procon/Justiça/advogado/Banco Central/exposição pública, desespero), Média (insatisfação e cobrança de solução, sem ameaça), Baixa (dúvidas e clientes satisfeitos/elogios). Distribuição ≈ 26% / 35% / 38%.
  - **Produtos (9 → 6 classes):** Empréstimo, Investimentos, Cartão de Crédito, Conta Corrente, Seguros e, como classe `SEM`, Consórcio, Financiamento Imobiliário, Previdência Privada e Câmbio. O fato do texto **sempre** pertence ao produto da linha.
  - **Canal:** Banco Central e Redes Sociais citam o próprio canal; Ouvidoria e SAC citam o histórico de contato; canais desconhecidos viram `Z`. Banco Central não recebe elogios.
  - **Status:** Resolvida concentra elogios ("meu caso foi resolvido"); Alta com Resolvida é rara (reincidência).
  - **Estilo:** caixa alta (raiva), sem acentos, aspas, CPF/e-mail/telefone (PII) em ~8% dos textos de Alta/Média.
- **Dataset** `tests/data/dataset_500.csv` = 500 válidas + 40 inválidas (id vazio/duplicado, data inválida, texto vazio, status inválido, combinações), variações de grafia (caixa, acento, espaços) e gabarito `dataset_500_expected.csv` (fila esperada, motivos, cenário).
- **Validações:** unicidade dos 500 textos (inclusive sem caixa/acento), coerência texto×produto/tom/canal/status, contagens, motivos de rejeição, **fila de cada linha** contra o gabarito, ordenação `_read` por verificador independente (canais por volume; Alta>Média>Baixa; Aberta>Em análise), uma chamada de IA por texto único, PII mascarada nos prompts, auditoria e relatório.
- **Dois modos:** (a) IA simulada "perfeita" (oráculo do gabarito) → fila 100% igual ao gabarito (valida o fluxo); (b) somente Motor de Regras de exemplo → piso de regressão ≥ 95% de concordância e nenhum erro grave (Alta tratada como Baixa).
- **Ciclo `_loop`:** todos respondidos; falha transitória recuperada na 2ª rodada; falha persistente → `_ok` parcial + `_loop` e fechamento no ciclo seguinte (ordem original restaurada); ciclos esgotados → `_nok`; erro de arquivo; lock; código de saída do CLI. Política aprovada vai verbatim e respostas geradas recebem o prefixo de revisão.
- **Implantação:** `challenge check` (ambiente, TXT, pastas, IA, concorrência), `--smoke` (ponta a ponta) e `--golden` (concordância com o gabarito: ≥ 90% e erros Alta→Baixa ≤ 1% das Alta).
- **Limite honesto:** o corpus é sintético e o Motor de Regras de exemplo foi escrito com vocabulário bancário geral, mas pelo mesmo autor: os números medem **regressão e fluxo**, não o desempenho em produção. Antes do Go-Live, rotule por humanos uma amostra de reclamações **reais** e meça a acurácia do modelo.

## 11. Implantação
Windows Task Scheduler: `challenge run-all --config C:\Challenge\config\settings.yaml` (recomenda-se repetir a tarefa periodicamente para consumir `_loop`). Lock órfão (`*.lock`) após queda: remover manualmente após confirmar que não há processo ativo.

## 12. Riscos
| Risco | Mitigação |
|---|---|
| Alucinação na resposta gerada | Política verbatim sempre que possível; prefixo de revisão; relatório destaca "Alta sem política". |
| Itens que nunca respondem | `max_loop_cycles` escala para `_nok`; relatório lista pendentes. |
| Deriva do modelo | Modelo/agente fixados; conjunto-ouro para regressão. |
| Variações de grafia de produto/status | Ampliar `*_MAP` em `domain/codes.py` ou normalizar na origem. |

## 13. Rastreabilidade
RF-01→`infra/io.py` · RF-02→`preprocess/validation.py` · RF-03→`domain/codes.py` · RF-04→`preprocess/tension.py`,`rules/engine.py` · RF-05/06→`preprocess/pipeline.py`,`domain/ordering.py` · RF-07→`performer/responder.py` · RF-08..11→`performer/pipeline.py` · RF-12→`logging_setup.py`,`reporting/*` · IA→`ai/*`.
