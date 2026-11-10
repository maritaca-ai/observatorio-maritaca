# Polygl0t/Tucano2-qwen-3.7B-Instruct — ResearchRubrics

**Nota: 2,5228** — denominador de **101 perguntas**, com **58 respostas julgadas** e **43 falhas de geração com zero**. Os 1449 critérios das respostas disponíveis foram julgados; os zeros adicionais não são veredictos de juiz.

Busca Serper; juiz S5 Instruct. Esta configuração não reproduz o leaderboard dos autores.

[Resumo](resumo.json) · [Casos zerados e motivos](casos-zerados.json) · [Protocolo](../../../../benchmarks/agentico/researchrubrics/README.md)

## Observações para o Observatório

- Os 101 casos foram tentados. 58 respostas foram julgadas; 43 falhas de geração recebem zero, mantendo 101 no denominador. Erros de transporte ou juiz não são zerados.
- Contexto nativo de 4096 tokens; teto explícito de 1024 tokens por saída, incluindo raciocínio. Reserva adicional zero e orçamento de entrada de 3072 bytes UTF-8 no runner.
- 40 respostas visíveis atingiram o teto e foram julgadas como recebidas, sem regeneração para melhorar qualidade.
- O Instruct realizou 176 chamadas web_search. 28 casos excederam o orçamento em bytes do runner, antes de novo pedido ao modelo; 15 saídas atingiram o teto contendo chamadas de ferramentas e não concluíram a pesquisa.
- A política inclui o orçamento em bytes e o teto de saída configurados no runner; isso não equivale a comprovar esgotamento do contexto nativo. Os motivos são publicados por caso. Não é uma regra original do scorer ResearchRubrics.

- Esta política é mais ampla que a usada nas campanhas nativas deste PR: aqui também são zeradas falhas nos limites configurados de entrada e saída, sem exigir três respostas vazias nem esgotamento do contexto nativo. DRACO do Tucano permanece parcial e não foi recalculado por esta política.

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
- [respostas-0010.json](respostas-0010.json) — 5 perguntas.
- [respostas-0011.json](respostas-0011.json) — 5 perguntas.
- [respostas-0012.json](respostas-0012.json) — 3 perguntas.

Os custos excluem GPU, busca e tentativas descartadas. Retornos web publicados apenas como URLs, títulos e hashes.
