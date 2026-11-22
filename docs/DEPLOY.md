# Guia de Implantação e Aceite — pacote StackSpot AI

Objetivo: preparar o ambiente e **provar**, em portões sequenciais (Gates), que a implantação funciona antes de entrar em produção. Cada gate tem comando, resultado esperado e ação em caso de falha. Só avance quando o gate anterior estiver verde.

## 1. Requisitos do ambiente
### 1.1 Comuns
| Item | Requisito | Verificação |
|---|---|---|
| Sistema | Windows 10/11 ou Server, 64 bits | `winver` |
| Python | 3.11+ com `venv` e `pip` | `py -3.11 --version` |
| Pacotes | `pandas`, `httpx`, `PyYAML` (+ `pytest`, `ruff`, `mypy` para os testes) | `pip install -e ".[dev]"` |
| Pastas | `C:\Challenge` com leitura/escrita para a conta que executa a tarefa | Gate 2 |
| Insumos de negócio | `motor_regras.txt` e `politica.txt` reais em `config\` | Gate 2 |
| Disco | ≥ 2 GB livres em `C:\Challenge` (logs, relatórios, CSVs) | Gate 2 |
| Conta de serviço | Usuário dedicado para o Task Scheduler, com "Log on as a batch job" | Gate 6 |

### 1.2 Específicos do StackSpot AI
| Item | Requisito | Verificação |
|---|---|---|
| Conta | Conta StackSpot com **Service Credential** (client_id e client_secret) e o **realm** | Portal StackSpot |
| Agente | Agente **dedicado** ao projeto, **sem Knowledge Sources**, instruções mínimas (ex.: "responda somente com o JSON solicitado no prompt"), LLM de sua escolha; anote o **Agent ID** | Gate 3 |
| Credenciais | Variáveis de ambiente `STACKSPOT_CLIENT_ID` e `STACKSPOT_CLIENT_SECRET` na **conta que roda a tarefa** (não ficam no YAML) | `challenge check` |
| Configuração | `stackspot_realm` e `stackspot_agent_id` em `config\settings.yaml` | Gate 3 |
| Rede (saída 443) | `idm.stackspot.com` (token) e `genai-inference-app.stackspot.com` (agente) liberados no firewall/proxy | `Test-NetConnection idm.stackspot.com -Port 443` e idem para o segundo host |
| Proxy corporativo | Se houver: `HTTPS_PROXY`/`NO_PROXY` no ambiente (o cliente HTTP os respeita) | Gate 3 |
| Inspeção TLS | Se o proxy re-assina certificados: apontar `SSL_CERT_FILE` para o bundle corporativo (.pem) | Gate 3 (erro de certificado) |
| Hardware | Nenhum modelo roda localmente: qualquer servidor com 2 vCPU e 4 GB de RAM atende ao volume deste projeto (estimativa; confirme com seu volume real) | Gate 4 |
| LGPD/contrato | Os textos das reclamações são enviados à plataforma (com `mask_pii: true`, CPF/CNPJ/e-mail/cartão/telefone são mascarados). Obtenha aprovação de segurança/jurídico | Fora do código |
| Limites da conta | Descubra o limite de requisições do seu plano; ajuste `llm_workers` | Gate 3 (concorrência) |

## 2. Portões de validação
### Gate 1 — Código e testes automatizados (sem IA real)
```powershell
pytest -q ; ruff check src tests ; mypy src
```
**Esperado:** todos os testes passam, sem erros de lint/tipos. Cobre: regras de fila, ordenação, rejeições, **corpus de 500 textos**, ciclo `_loop`, clientes HTTP, configuração, verificação de implantação. **Falhou?** Não prossiga: ambiente Python/dependências incorretos.

### Gate 2 — Ambiente e arquivos (`challenge check`)
```powershell
challenge check --config config\settings.yaml
```
**Esperado:** nenhum `FAIL`. Verifica Python, TXT de regras/política (parse), escrita em todas as pastas, espaço em disco e o schema do CSV de entrada. `WARN` em `entrada` é aceitável se o arquivo ainda não chegou.

### Gate 3 — Conectividade e IA real
Mesmo comando do Gate 2; observe as linhas `ia:*`.
- `ia:tensao` PASS: autenticação (token), chamada ao agente e JSON válido; a probe usa um texto com "Procon" e espera **Alta**.
- `ia:resposta` PASS: o agente respondeu no contrato (política ou texto).
- `ia:concorrencia` PASS: `llm_workers` simultâneos sem erro. **WARN/FAIL ⇒ reduza `llm_workers`** (possível HTTP 429).
- Falhas típicas: `Falha de autenticação` (credencial/realm errados), `IA indisponível ou resposta inválida` (instruções do agente atrapalham o formato — simplifique-as), erro de certificado (ver `SSL_CERT_FILE`), timeout (aumente `llm_timeout_s` ou verifique o proxy).

### Gate 4 — Ponta a ponta em amostra (não toca na produção)
```powershell
challenge check --smoke --rows 40
```
Executa o Processo 1 e o Performer **reais** em pasta temporária. **Esperado:** `smoke` PASS (ou WARN se sobraram pendentes em `_loop`, o que é um comportamento válido). `FAIL` = algum lote terminou em `_nok`.

### Gate 5 — Aceite com o dataset de 500 casos (gabarito)
```powershell
challenge check --golden                    # 500 textos distintos (500 chamadas à IA)
challenge check --golden --golden-rows 150  # amostra menor, para uma 1ª rodada rápida
```
O dataset tem **500 reclamações bancárias distintas** (empréstimo, investimentos, cartão, conta, seguros, consórcio, financiamento, previdência e câmbio), de clientes prestes a ameaçar (Procon, Justiça, Banco Central, redes sociais) a clientes satisfeitos, sempre coerentes com produto, canal e status. Tempo estimado: proporcional a 500 chamadas à IA ÷ `llm_workers`.

**Critérios de aceite:**
| Verificação | Critério |
|---|---|
| `golden:rejeicoes` | exatamente o do gabarito (40 no arquivo completo) |
| `golden:canal+produto+status` | **0 divergências** (parte determinística) |
| `golden:tensao` | ≥ **90%** de concordância **e** erros graves (Alta classificada como Baixa) ≤ **1%** das Alta |

A linha `golden:tensao` mostra a matriz de divergências (esperado→obtido), por exemplo `M→B:12` (Média tratada como Baixa). Divergências concentradas em Média↔Baixa são toleráveis; **Alta→Baixa não**: ajuste o prompt/agente ou o Motor de Regras (termos com *piso*) antes de prosseguir.
**Limite:** o corpus é sintético. Antes do Go-Live, rotule por humanos uma amostra de reclamações **reais** e compare (alvo sugerido: ≥ 95% de acordo nos casos Alta).

### Gate 6 — Piloto em homologação
1. Copie `tests\data\dataset_500.csv` para `C:\Challenge\dataset_challenge.csv` (ambiente de homologação).
2. `challenge run-all` e confira: `Fila\`, `Output\..._ok.csv` (e eventual `_loop`), `Relatorios\*.html` (Resumo, Tendências, Top Riscos) e `Logs\`.
3. Rode `challenge perform` de novo e confirme que **só** os `_loop` são reprocessados; ao fim não deve restar `_loop` nem `.state.json`.
4. Agende com a conta de serviço: `schtasks /Create /SC HOURLY /TN "Challenge" /TR "...\challenge.exe run-all --config ...\settings.yaml" /RU <conta>`; valide uma execução agendada (as variáveis de ambiente precisam existir **para essa conta**).
5. Revise 20 respostas `[Sugestão IA - revisar]` com o time de atendimento.

## 3. Go / No-Go
**GO** quando: Gates 1–6 verdes; nenhuma linha `FAIL` em `challenge check`; piloto sem `_nok`; concordância de tensão em amostra real ≥ meta; aprovação de segurança/LGPD; conta de serviço validada no agendador.
**NO-GO** se: qualquer `FAIL`; `_nok` no piloto; `WARN` de concorrência não tratado; credenciais em arquivo versionado.

## 4. Operação e rollback
- Monitorar: `Logs\*.log` (JSON), `stats_*.json`, `relatorio_*.html`; alertar em código de saída ≠ 0 e em `_nok`.
- Lock órfão (`*.lock` em `Output\`) após queda: apagar somente após confirmar que não há processo ativo.
- Rollback: desabilitar a tarefa agendada; os arquivos em `Output\` e `Fila\` permanecem íntegros (a entrada nunca é alterada). Para operar sem IA, `llm_provider: none` (somente regras; itens sem política vão para `_loop`).

## 5. Diagnóstico rápido
| Sintoma | Causa provável | Ação |
|---|---|---|
| Exit 2 | Config/entrada inválida | Ler a mensagem `ERRO:`; rodar `challenge check` |
| Exit 1 | Há `_loop`/`_nok` | Ver `stats_performer_*` e `audit_performer_*` (campo `erro`) |
| Muitos itens em `_loop` | IA lenta/limitada | Reduzir `llm_workers`, aumentar `llm_timeout_s`, agendar com mais frequência |
| `_nok` após ciclos | Itens persistentemente sem resposta | Revisar texto/política; tratar manualmente |
