# Benchmarks

Os forks contêm o código utilizado, separado por categoria. As fontes, revisões e
licenças disponíveis permanecem junto de cada implementação. A adaptação de saída
leva os registros finais ao mesmo formato de `results/`; não altera os textos
gerados nem pede novos julgamentos.

| Benchmark | Categoria | População executada | Fonte e protocolo |
|---|---|---:|---|
| [MMLU PT](provas/mmlu_pt/README.md) | provas | 7233 + 19347 | [Protocolo](provas/mmlu_pt/protocol.json) · [Original](https://huggingface.co/datasets/mmlu-pt/mmlu-pt-high-school-full) |
| [Global MMLU PT](provas/global_mmlu_pt/README.md) | provas | 14042 | [Protocolo](provas/global_mmlu_pt/protocol.json) · [Original](https://huggingface.co/datasets/CohereForAI/Global-MMLU) |
| [ENADE-QA](provas/enade_qa/README.md) | provas | 716 | [Protocolo](provas/enade_qa/protocol.json) · [Original](https://github.com/H2IA/ENADE-QA) |
| [ENEM-VL · text](provas/enem_vl/README.md) | provas | 1988 | [Protocolo](provas/enem_vl/protocol.json) · [Original](https://github.com/graphs4ai/enem-vl-code) |
| [BLUEX v2 · text](provas/bluex_v2/README.md) | provas | 395 | [Protocolo](provas/bluex_v2/protocol.json) · [Original](https://github.com/TropicAI-Research/BLUEX-V2) |
| [MARCA public](agentico/marca/README.md) | agentico | 104 | [Protocolo](agentico/marca/protocol.json) · [Original](https://github.com/maritaca-ai/MARCA) |
| [CAPITU](instrucoes/capitu/README.md) | instrucoes | 200 + 100 | [Protocolo](instrucoes/capitu/protocol.json) · [Original](https://github.com/maritaca-ai/capitu) |
| [MATH-PT · PT-BR MC](provas/math_pt/README.md) | provas | 638 | [Protocolo](provas/math_pt/protocol.json) · [Original](https://huggingface.co/datasets/tiagoteixeira03/MATH-PT) |
| [BRoverbs](brasil_especifico/broverbs/README.md) | brasil especifico | 1158 | [Protocolo](brasil_especifico/broverbs/protocol.json) · [Original](https://huggingface.co/datasets/Tropic-AI/BRoverbs) |
| [ASSIN 2 RTE](brasil_especifico/assin_rte/README.md) | brasil especifico | 300 | [Protocolo](brasil_especifico/assin_rte/protocol.json) · [Original](https://huggingface.co/datasets/nilc-nlp/assin2) |
| [Lumen PT · variante GPT-4.1](seguranca_etica/lumen/README.md) | seguranca etica | 1296 + 22 | [Protocolo](seguranca_etica/lumen/protocol.json) · [Original](https://github.com/TropicAI-Research/lumen) |
| [BrowseComp-Plus · BM25 · val100](agentico/browsecomp_plus/README.md) | agentico | 100 | [Protocolo](agentico/browsecomp_plus/protocol.json) · [Original](https://github.com/texttron/BrowseComp-Plus) |
| [Prosa-PT · rubricas filtradas](chat/prosa_pt/README.md) | chat | 1000 | [Protocolo](chat/prosa_pt/protocol.json) · [Original](https://github.com/maritaca-ai/Prosa) |
| [IFBench · teste completo](instrucoes/ifbench/README.md) | instrucoes | 300 | [Protocolo](instrucoes/ifbench/protocol.json) · [Original](https://github.com/allenai/IFBench) |
| [Arena-Hard v2 · 150 · Luna medium](chat/arena_hard_v2/README.md) | chat | 150 | [Protocolo](chat/arena_hard_v2/protocol.json) · [Original](https://github.com/lmarena/arena-hard-auto) |
| [CulturalBench-Hard · completo + Brasil](brasil_especifico/culturalbench/README.md) | brasil especifico | 4908 | [Protocolo](brasil_especifico/culturalbench/protocol.json) · [Original](https://github.com/appier-research/language-matters) |
| [SOB · completo](saida_estruturada/sob/README.md) | saida estruturada | 5324 | [Protocolo](saida_estruturada/sob/protocol.json) · [Original](https://github.com/InterfazeAI/sob) |
| [LongBench v2 · completo](contexto_longo/longbench_v2/README.md) | contexto longo | 503 | [Protocolo](contexto_longo/longbench_v2/protocol.json) · [Original](https://github.com/THUDM/LongBench) |
| [HarmBench · texto · DirectRequest](seguranca_etica/harmbench/README.md) | seguranca etica | 320 | [Protocolo](seguranca_etica/harmbench/protocol.json) · [Original](https://github.com/centerforaisafety/HarmBench) |
| [CondutaBench · amostra de 140 · Sabiá-4-Thinking](medico/conduta_bench/README.md) | medico | 140 | [Protocolo](medico/conduta_bench/protocol.json) · [Original](https://github.com/TropicAI-Research/CondutaBench) |
| [OAB-Bench · completo 39–44](juridico/oab_bench/README.md) | juridico | 210 | [Protocolo](juridico/oab_bench/protocol.json) · [Original](https://github.com/maritaca-ai/oab-bench) |
| [Magis-Bench](juridico/magis_bench/README.md) | juridico | 74 | [Protocolo](juridico/magis_bench/protocol.json) · [Original](https://github.com/maritaca-ai/magis-bench) |

Arena-Hard conserva os 100 prompts principais na nota; os 50 criativos não
entram nessa média. Prosa tem 981 conversas elegíveis entre as 1.000 perguntas.
A nota do Structured Output Benchmark usa os 5.000 exemplos textuais. OAB
compreende as edições 39–44, sete áreas, 210 questões. Conduta usa o recorte fixado
de 140 questões. Lumen registra os 22 controles benignos além dos 1.296 testes
de ações nocivas. MMLU PT e CAPITU produzem mais de uma métrica.

O protocolo MMLU desta campanha é o adaptador de chat registrado: não implica
equivalência com protocolos de likelihood. Cada preset e diferença estão
declarados nos arquivos de protocolo e em `profiles/`.

Para conferir os arquivos dos forks e a cobertura da matriz, sem rede:

```bash
python scripts/verify_sources.py
```

O diretório `fork/` conserva o subconjunto de código utilizado. Não inclui o
histórico Git do projeto original, pesos de modelos nem dependências sem uso na
avaliação. Dados necessários à execução são preparados nas revisões fixadas.

## Runners disponíveis para novas avaliações

As implementações abaixo podem gerar, importar e julgar relatórios. Não há
resultados novos incluídos nesta entrega, nem alteração da matriz histórica.

| Benchmark | População | Execução e protocolo |
|---|---:|---|
| DRACO | 100 perguntas; 3.934 critérios | [Instruções](agentico/draco/README.md) · [Protocolo](agentico/draco/protocol.json) |
| ResearchRubrics | 101 perguntas; 2.593 critérios | [Instruções](agentico/researchrubrics/README.md) · [Protocolo](agentico/researchrubrics/protocol.json) |

Teste offline dos runners (sem inferência, busca ou julgamento):

```bash
PYTHONPATH=benchmarks/agentico/draco/fork uv run --no-project --python 3.13 \
  --with pytest --with httpx --with numpy --with scipy \
  python -m pytest tests/deep_research --import-mode=importlib -q
```
