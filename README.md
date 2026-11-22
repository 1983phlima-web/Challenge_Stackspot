# Challenge Automation — pacote **StackSpot AI**

Triagem de reclamações usando um **agente StackSpot AI** (Agents API, REST, sem streaming).

## Pré-requisitos
- Windows 10/11 ou Server, Python 3.11+
- Conta StackSpot com **Service Credential** (client_id/client_secret) e o **realm** da conta
- Um **agente dedicado** no portal: instruções mínimas (ex.: "responda apenas com o JSON pedido no prompt"), **sem Knowledge Sources**, com o LLM de sua escolha. As configurações do agente valem em toda chamada; o prompt do sistema deste projeto segue dentro do `user_prompt`.

## Instalação
```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## Configuração
1. **Substitua** `config\motor_regras.txt` e `config\politica.txt` pelos seus TXT (SPEC §5.3–5.4).
2. Em `config\settings.yaml` informe `stackspot_realm` e `stackspot_agent_id`.
3. Defina as credenciais **no ambiente** (veja `env.example`):
   ```powershell
   $env:STACKSPOT_CLIENT_ID = "<client_id>"
   $env:STACKSPOT_CLIENT_SECRET = "<client_secret>"
   ```
4. Mantenha `mask_pii: true`: os textos são enviados à plataforma. Valide o enquadramento LGPD/contratual com seu time de segurança.

## Execução
```powershell
challenge preprocess   # Processo 1
challenge perform      # Processo 2 (com ciclo _loop)
challenge run-all      # ambos
```

## Pastas e arquivos gerados
```
C:\Challenge\
  dataset_challenge.csv          (entrada)
  Fila\       processadas_<ts>.csv · rejeitadas_<ts>.csv
  Output\     processadas_<ts>_read.csv  →  _ok.csv (respondidos) | _loop.csv (pendentes) | _nok.csv (humano)
  Logs\       *.log (JSON) · audit_*.jsonl · stats_*.json
  Relatorios\ relatorio_*.md / .html   (Resumo, Tendências, Top Riscos)
```

## Ciclo `_loop` (itens sem resposta)
| Situação | Resultado |
|---|---|
| Todos respondidos | `<lote>_ok.csv` completo, na ordem da fila; nada pendente |
| Alguns sem resposta | respondidos → `_ok.csv`; **só os pendentes** → `_loop.csv` (sem coluna `Resposta`) |
| Mesma execução | pendentes ganham `loop_rounds_per_run − 1` rodada(s) extra(s) |
| Ainda pendentes | `_loop.csv` espera a **próxima execução** (agende a tarefa periodicamente) |
| `max_loop_cycles` atingido | pendentes → `_nok.csv` para análise humana |
| Arquivo ilegível / colunas ausentes | `_nok.csv` |

Códigos de saída: `0` tudo concluído · `1` há `_loop`/`_nok` · `2` entrada/config inválida · `3` erro inesperado.

## Operação
```powershell
challenge run-all --config C:\Challenge\config\settings.yaml
schtasks /Create /SC HOURLY /TN "Challenge" /TR "C:\Challenge\.venv\Scripts\challenge.exe run-all --config C:\Challenge\config\settings.yaml"
```
Lock órfão (`*.lock` em `Output\`) após queda: apague só depois de confirmar que nenhum processo está ativo.

## Testes e validação com 500 casos
```powershell
pytest -q                 # suíte completa (inclui o dataset de 500 casos com gabarito)
ruff check src tests ; mypy src
python tests\dataset_factory.py --valid 500 --invalid 40 --out C:\Challenge\dataset_challenge.csv --expected gabarito.csv
```
`tests\data\dataset_500.csv` traz **500 reclamações bancárias distintas** (clientes que ameaçam, insatisfeitos e satisfeitos, em 9 produtos) **mais 40 linhas inválidas** (540 linhas). `dataset_500_expected.csv` é o gabarito: fila esperada, motivo da rejeição e cenário por linha. O gerador é `tests\corpus.py`. Copie o CSV para `C:\Challenge\dataset_challenge.csv` para uma validação ponta a ponta com a IA real.

## Validação da implantação
```powershell
challenge check                 # ambiente, TXT, pastas, IA (tensão, resposta, concorrência)
challenge check --smoke --rows 40   # Processos 1 e 2 reais em amostra temporária
challenge check --golden        # 500 textos distintos vs. gabarito (use --golden-rows 150 para amostra)
```
Saída `0` = sem FAIL; `1` = há FAIL. Relatório JSON em `Logs\preflight_<ts>.json`. Roteiro completo, com critérios de aceite e Go/No-Go, em `docs\DEPLOY.md`.

## Documentação
`docs\DEPLOY.md` (requisitos do ambiente e gates de aceite) · `docs\SPEC.md` (requisitos, contratos, regras, estados) · `docs\C4.md` (C4 níveis 1–4, dinâmico, estados, implantação) · `docs\ADR.md`.

## Dicas para StackSpot
- HTTP 429 e 5xx são retentados com backoff; HTTP 401 renova o token automaticamente. Credencial inválida interrompe com erro claro (código de saída 3).
- Se a conta limitar requisições, reduza `llm_workers`; o que falhar vai para `_loop`.
- Endpoints usados: `https://idm.stackspot.com/{realm}/oidc/oauth/token` e `https://genai-inference-app.stackspot.com/v1/agent/{agent_id}/chat` (sobrescreva com `stackspot_auth_url` e `llm_base_url` se sua conta usar outro host).
