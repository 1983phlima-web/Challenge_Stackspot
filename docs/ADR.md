# Decisões de Arquitetura (ADR)

**ADR-001 — Híbrido Regras + IA para tensão.** A IA interpreta contexto; o Motor de Regras dá evidência auditável, piso para termos críticos e fallback determinístico.

**ADR-002 — Provedor de IA plugável (Protocol + fábrica preguiçosa).** `LLMClient` desacopla o domínio. Cada pacote distribuído contém só o seu provedor (StackSpot AI); a fábrica importa o módulo sob demanda e falha com mensagem clara se ele não estiver no pacote.

**ADR-003 — Política verbatim, IA só decide/gera.** A IA nunca reescreve política aprovada; escolhe um ID dentre candidatas pré-filtradas ou, na ausência, sugere resposta marcada para revisão.

**ADR-004 — Handoff por arquivo, escrita atômica e lock.** `.tmp`→`os.replace` publica `_read`; `.lock` com `O_EXCL` evita duplo processamento. Evolução natural: fila de mensagens.

**ADR-005 — Pandas com dtype texto.** Evita coerções silenciosas; validação explícita em `validation.py`.

**ADR-006 — Máscara de PII na borda da IA.** O CSV permanece íntegro; só o payload enviado ao modelo é mascarado.

**ADR-007 — Falha parcial gera `_loop`, não `_nok`.** Um item ruim não bloqueia o lote: respondidas vão para `_ok` (acumulado, ordem original via `state.json`), pendentes para `_loop` e são retentadas (mesma execução e execuções seguintes). `max_loop_cycles` impede laço infinito: esgotado, vai para `_nok` para análise humana. Escrita em ordem `_ok` → `_loop` → remoção da origem torna a reexecução idempotente (deduplicação por `id`).

**ADR-008 — Dataset de 500 casos com gabarito independente.** A fila esperada e a ordenação são recalculadas nos testes por um verificador separado do código de produção, evitando testes tautológicos.
