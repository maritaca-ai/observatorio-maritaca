# Polygl0t/Tucano2-qwen-3.7B-Think — ResearchRubrics

**Sem nota final.** 88/101 perguntas julgadas; 2253 critérios avaliados. Média parcial: **5,7955**, apenas entre as respostas julgadas.

Busca Serper; juiz S5 Instruct. Esta configuração não reproduz o leaderboard dos autores.

[Resumo](resumo.json) · [Casos sem nota](casos-sem-nota.json) · [Protocolo](../../../../benchmarks/agentico/researchrubrics/README.md)

## Observações para o Observatório

- Os 101 casos foram tentados. Não há nota completa; a média parcial usa somente respostas julgadas e não deve entrar no ranking como resultado final.
- Contexto nativo de 4096 tokens; teto explícito de 1024 tokens por saída, incluindo raciocínio. Reserva adicional zero e orçamento de entrada de 3072 bytes UTF-8 no runner.
- 63 respostas visíveis atingiram o teto e foram julgadas como recebidas, sem regeneração para melhorar qualidade.
- O Thinking não realizou buscas, apesar das ferramentas disponíveis. 13 casos consumiram o teto de saída sem produzir resposta final.

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
- [respostas-0012.json](respostas-0012.json) — 5 perguntas.
- [respostas-0013.json](respostas-0013.json) — 5 perguntas.
- [respostas-0014.json](respostas-0014.json) — 5 perguntas.
- [respostas-0015.json](respostas-0015.json) — 5 perguntas.
- [respostas-0016.json](respostas-0016.json) — 5 perguntas.
- [respostas-0017.json](respostas-0017.json) — 5 perguntas.
- [respostas-0018.json](respostas-0018.json) — 3 perguntas.

Os custos excluem GPU, busca e tentativas descartadas. Retornos web publicados apenas como URLs, títulos e hashes.
