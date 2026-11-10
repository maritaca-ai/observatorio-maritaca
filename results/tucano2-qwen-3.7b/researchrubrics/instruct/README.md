# Polygl0t/Tucano2-qwen-3.7B-Instruct — ResearchRubrics

**Sem nota final.** 58/101 perguntas julgadas; 1449 critérios avaliados. Média parcial: **4,3932**, apenas entre as respostas julgadas.

Busca Serper; juiz S5 Instruct. Esta configuração não reproduz o leaderboard dos autores.

[Resumo](resumo.json) · [Casos sem nota](casos-sem-nota.json) · [Protocolo](../../../../benchmarks/agentico/researchrubrics/README.md)

## Observações para o Observatório

- Os 101 casos foram tentados. Não há nota completa; a média parcial usa somente respostas julgadas e não deve entrar no ranking como resultado final.
- Contexto nativo de 4096 tokens; teto explícito de 1024 tokens por saída, incluindo raciocínio. Reserva adicional zero e orçamento de entrada de 3072 bytes UTF-8 no runner.
- 40 respostas visíveis atingiram o teto e foram julgadas como recebidas, sem regeneração para melhorar qualidade.
- O Instruct realizou 176 chamadas web_search. 28 casos excederam o orçamento em bytes do runner, antes de novo pedido ao modelo; 15 saídas atingiram o teto contendo chamadas de ferramentas e não concluíram a pesquisa.

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
