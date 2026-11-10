# Polygl0t/Tucano2-qwen-3.7B-Instruct · Instruct — DRACO

**Nota: 1,4384** — denominador de **100 perguntas**, com **48 respostas julgadas** e **52 falhas de geração com zero**.

Média por pergunta dos pesos satisfeitos / soma dos pesos positivos × 100; limitada a [0, 100] por pergunta.

Busca Serper; juiz S5 Instruct (`reasoning_effort=none`). Esta configuração não reproduz o leaderboard dos autores.

[Resumo e proveniência](resumo.json) · [Protocolo](../../../../benchmarks/agentico/draco/README.md)

## Respostas e julgamentos

- [respostas-0001.json](respostas-0001.json) — 5 perguntas.
- [respostas-0002.json](respostas-0002.json) — 5 perguntas.
- [respostas-0003.json](respostas-0003.json) — 5 perguntas.
- [respostas-0004.json](respostas-0004.json) — 5 perguntas.
- [respostas-0005.json](respostas-0005.json) — 5 perguntas.
- [respostas-0006.json](respostas-0006.json) — 5 perguntas.
- [respostas-0007.json](respostas-0007.json) — 5 perguntas.
- [respostas-0008.json](respostas-0008.json) — 5 perguntas.
- [respostas-0009.json](respostas-0009.json) — 5 perguntas.
- [respostas-0010.json](respostas-0010.json) — 3 perguntas.

## Observações para o Observatório

- O Instruct realizou 274 buscas web em 87 dos 100 casos e 13 leituras de páginas.
- Os 100 casos foram tentados: 48 respostas julgadas e 52 falhas de geração com zero, mantendo 100 no denominador.
- 37 casos excederam a janela de contexto após acumular histórico; 15 esgotaram as tentativas por limite de saída.
- As falhas por limite de saída incluem texto truncado rejeitado pelo runner nativo após três tentativas; não significam necessariamente resposta vazia. Esses casos recebem zero por consolidação e não por julgamento de rubricas.
- Política de consolidação attempted-generation-failure-zero-v1, também usada no ResearchRubrics do Tucano. É mais ampla que os critérios de resposta vazia/contexto das demais campanhas; não é regra original do scorer. Erros de transporte e juiz não são convertidos em zero.

[Casos zerados e motivos](casos-zerados.json). Os zeros não são veredictos de juiz.

Os tokens cobrem os turnos selecionados da pesquisa e os julgamentos selecionados. Tentativas descartadas não entram nos custos; valores não informados são `null`. Custos de GPU e busca não estão incluídos.

Retornos web publicados apenas como URLs, títulos e hashes, sem texto integral de páginas.
