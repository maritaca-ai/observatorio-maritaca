# Observatório Maritaca

**11 modelos de linguagem · 24 benchmarks · 1.081.170 instâncias de avaliação**

[**Acessar o Observatório Maritaca →**](https://maritaca-ai.github.io/observatorio-maritaca/)

A Maritaca avaliou o S5-nano e dez modelos brasileiros e internacionais em tarefas
de conversa, seguimento de instruções, segurança, conhecimento, uso de ferramentas,
saída estruturada e contexto longo, incluindo testes de cultura brasileira,
direito e medicina. A comparação reúne avaliações nos modos Thinking e Instruct.

Este repositório contém as notas, as respostas dos modelos, os julgamentos e os
protocolos usados em cada benchmark.

<!-- BEGIN VERIFIED RESULTS -->

## Resultados

Médias e notas finais, separadas por modo. Os melhores valores de cada coluna de média ou linha de benchmark aparecem em **negrito**.

### Thinking

| Posição | Modelo | Nativo BR | Traduzido PT | Não nativo | Total | Testes |
|---:|---|---:|---:|---:|---:|---:|
| 1 | S5-nano 🇧🇷 | **83,74** | 86,94 | **55,46** | **74,05** | 25/25 |
| 2 | Qwen3.5-4B | 72,49 | **87,61** | 54,37 | 67,41 | 25/25 |
| 3 | LFM2.5-24B-A2B | 69,68 | 87,30 | 52,53 | 64,80 | 25/25 |
| 4 | Nemotron 3.5 Bolt E4B | 71,42 | 84,92 | 46,08 | 62,12 | 25/25 |
| 5 | Gemma 4 E4B | 71,64 | 83,82 | 43,45 | 61,01 | 25/25 |
| 6 | LFM3-1.7B | 57,60 | 74,76 | 49,41 | 56,89 | 25/25 |
| 7 | Lumi 4B 🇧🇷 | 52,68 | 52,50 | 30,19 | 42,55 | 25/25 |
| 8 | Tucano2-qwen-3.7B 🇧🇷 | 34,83 | 46,12 | 24,76 | 30,78 | 24/25 |

<details>
<summary>Resultados por benchmark · Thinking</summary>

| Benchmark | S5-nano 🇧🇷 | Qwen3.5-4B | LFM2.5-24B-A2B | Nemotron 3.5 Bolt E4B | Gemma 4 E4B | LFM3-1.7B | Lumi 4B 🇧🇷 | Tucano2-qwen-3.7B 🇧🇷 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Arena-Hard v2 | 19,12 | 11,67 | 21,65 | **25,82** | 20,06 | 11,18 | 3,62 | 0,35 |
| Prosa-PT | **75,07** | 56,89 | 54,41 | 59,87 | 60,14 | 51,24 | 30,90 | 25,94 |
| IFBench | 42,67 | 49,67 | **71,67** | 59,67 | 37,33 | 68,67 | 23,67 | 12,33 |
| CAPITU | 95,50 | 90,00 | **98,00** | 89,00 | 85,00 | 96,00 | 65,00 | 50,00 |
| CAPITU · conversas completas | **97,00** | 92,00 | 95,00 | 81,00 | 74,00 | 94,00 | 37,00 | 33,00 |
| Lumen PT | 98,92 | 94,75 | 91,51 | **99,92** | 99,23 | 77,62 | 98,23 | — |
| HarmBench | 91,25 | **96,56** | 89,06 | 91,56 | 83,12 | 84,69 | 94,69 | 90,62 |
| MMLU-PT · ensino médio | **82,83** | 81,85 | 75,53 | 74,62 | 74,81 | 53,31 | 59,98 | 3,57 |
| MMLU-PT · graduação | **80,54** | 63,92 | 57,82 | 64,42 | 65,04 | 42,70 | 47,84 | 9,66 |
| Global-MMLU PT | 78,22 | **81,43** | 79,27 | 75,84 | 73,64 | 62,28 | 44,37 | 3,34 |
| ENADE-QA | **81,70** | 79,75 | 74,58 | 72,63 | 72,07 | 60,34 | 61,73 | 50,98 |
| ENEM-VL · texto | **92,91** | 92,00 | 84,46 | 90,59 | 88,83 | 81,29 | 80,18 | 71,38 |
| BLUEX v2 · texto | **87,89** | 84,46 | 82,60 | 80,03 | 82,89 | 81,50 | 65,16 | 62,71 |
| MATH-PT · PT-BR | 87,77 | **91,07** | 90,75 | 80,72 | 85,58 | 85,42 | 81,50 | 20,06 |
| MARCA público | **89,57** | 78,23 | 66,82 | 40,01 | 35,11 | 79,32 | 2,15 | 5,61 |
| BrowseComp-Plus | **37,00** | 27,00 | 28,00 | 7,00 | 8,00 | 29,00 | 4,00 | 0,00 |
| DRACO | **61,47** | 53,63 | 35,95 | 28,60 | 28,26 | 43,32 | 10,99 | 4,69 |
| ResearchRubrics | **58,85** | 52,00 | 41,70 | 30,65 | 32,25 | 46,47 | 22,89 | 5,05 |
| Structured Output Benchmark | 97,33 | 96,64 | 98,19 | 94,91 | 93,94 | **98,40** | 86,46 | 70,78 |
| BRoverbs | **92,83** | 79,97 | 68,91 | 87,13 | 82,73 | 40,76 | 31,35 | 69,43 |
| ASSIN 2 · RTE | **95,67** | 93,80 | 95,33 | 94,00 | 94,00 | 87,24 | 60,62 | 88,89 |
| CulturalBench Hard | 41,73 | **48,08** | 47,60 | 41,32 | 44,34 | 29,01 | 16,22 | 29,10 |
| LongBench v2 | 49,70 | **54,08** | 38,97 | 35,19 | 43,74 | 34,00 | 9,15 | 9,94 |
| OAB-Bench · 210 · completo | **82,00** | 45,88 | 40,83 | 50,43 | 53,19 | 27,93 | 31,18 | 25,39 |
| Magis-Bench · 74 · completo | **50,41** | 13,97 | 15,42 | 21,86 | 23,38 | 7,81 | 4,50 | 3,33 |
| CondutaBench · 140 | **80,24** | 67,92 | 70,98 | 57,27 | 58,49 | 42,81 | 27,33 | 25,47 |

</details>

### Instruct

| Posição | Modelo | Nativo BR | Traduzido PT | Não nativo | Total | Testes |
|---:|---|---:|---:|---:|---:|---:|
| 1 | S5-nano 🇧🇷 | **74,65** | 83,48 | **47,02** | **65,78** | 25/25 |
| 2 | Qwen3.5-4B | 66,22 | **84,94** | 45,80 | 60,17 | 25/25 |
| 3 | Nemotron 3.5 Bolt E4B | 67,58 | 81,16 | 41,83 | 57,65 | 25/25 |
| 4 | Gemma 4 E4B | 68,10 | 77,91 | 40,95 | 57,39 | 25/25 |
| 5 | LatamGPT 70B | 47,66 | 66,97 | 42,99 | 48,19 | 20/25 |
| 6 | LFM3-1.7B | 47,17 | 11,57 | 39,60 | 42,17 | 25/25 |
| 7 | Gaia 4B 🇧🇷 | 46,25 | 66,90 | 31,65 | 41,41 | 25/25 |
| 8 | Lumi 4B 🇧🇷 | 43,40 | 59,48 | 31,92 | 38,95 | 25/25 |
| 9 | Tucano2-qwen-3.7B 🇧🇷 | 31,87 | 40,97 | 20,12 | 27,53 | 25/25 |
| 10 | Manacá 🇧🇷 | 7,01 | 27,76 | 19,56 | 12,85 | 20/25 |

<details>
<summary>Resultados por benchmark · Instruct</summary>

| Benchmark | S5-nano 🇧🇷 | Qwen3.5-4B | Nemotron 3.5 Bolt E4B | Gemma 4 E4B | LatamGPT 70B | LFM3-1.7B | Gaia 4B 🇧🇷 | Lumi 4B 🇧🇷 | Tucano2-qwen-3.7B 🇧🇷 | Manacá 🇧🇷 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Arena-Hard v2 | 4,67 | 10,01 | **19,31** | 18,47 | 3,41 | 2,86 | 1,00 | 1,45 | 0,33 | 0,00 |
| Prosa-PT | **64,70** | 57,12 | 58,11 | 58,45 | 27,89 | 40,00 | 42,28 | 35,21 | 20,44 | 7,66 |
| IFBench | 27,33 | 30,67 | **45,00** | 30,00 | 14,33 | 31,67 | 20,00 | 22,33 | 13,33 | 17,33 |
| CAPITU | 68,50 | 70,50 | 78,50 | **84,00** | 62,50 | 73,00 | 74,00 | 69,50 | 54,00 | 17,00 |
| CAPITU · conversas completas | 76,00 | 73,00 | 69,00 | **78,00** | 61,00 | 63,00 | 67,00 | 58,00 | 26,00 | 7,00 |
| Lumen PT | **99,38** | 93,52 | 97,53 | 96,37 | — | 83,56 | 66,36 | 85,65 | 61,81 | — |
| HarmBench | 85,00 | **95,00** | 92,19 | 90,31 | 88,12 | 87,19 | 76,25 | 90,31 | 83,44 | 94,06 |
| MMLU-PT · ensino médio | 70,81 | **76,84** | 72,63 | 73,73 | 42,32 | 48,42 | 41,61 | 38,52 | 1,47 | 0,97 |
| MMLU-PT · graduação | **69,66** | 59,60 | 64,40 | 65,28 | 51,57 | 40,62 | 43,24 | 38,00 | 1,48 | 0,14 |
| Global-MMLU PT | 72,96 | **75,88** | 69,66 | 61,83 | 44,71 | 21,83 | 46,44 | 38,35 | 5,62 | 12,36 |
| ENADE-QA | **71,79** | 66,48 | 64,11 | 66,34 | 57,96 | 40,08 | 41,48 | 46,79 | 44,83 | 22,49 |
| ENEM-VL · texto | **78,57** | 76,06 | 75,25 | 76,01 | 76,81 | 54,68 | 59,81 | 66,00 | 71,08 | 18,06 |
| BLUEX v2 · texto | **85,60** | 80,49 | 80,51 | 80,00 | 72,16 | 70,56 | 66,06 | 66,46 | 41,07 | 3,00 |
| MATH-PT · PT-BR | 82,29 | **84,95** | 78,68 | 83,70 | 12,07 | 84,64 | 27,12 | 27,90 | 7,52 | 0,00 |
| MARCA público | **83,86** | 61,31 | 23,96 | 25,14 | — | 61,37 | 15,33 | 3,41 | 11,02 | — |
| BrowseComp-Plus | **25,00** | 17,00 | 5,00 | 7,00 | — | 6,00 | 1,00 | 1,00 | 1,00 | — |
| DRACO | **60,74** | 39,79 | 23,99 | 25,79 | — | 39,55 | 16,59 | 13,86 | 1,44 | — |
| ResearchRubrics | **54,03** | 42,00 | 26,49 | 30,51 | — | 41,52 | 23,63 | 27,27 | 2,52 | — |
| Structured Output Benchmark | 92,05 | 94,32 | 96,89 | 93,44 | **97,71** | 86,81 | 97,69 | 96,31 | 52,34 | 0,00 |
| BRoverbs | 87,13 | 81,78 | **87,48** | 73,32 | 78,41 | 22,02 | 63,30 | 41,88 | 75,47 | 14,08 |
| ASSIN 2 · RTE | **94,00** | 94,00 | 92,67 | 94,00 | 89,23 | 1,30 | 87,36 | 80,60 | 76,32 | 43,17 |
| CulturalBench Hard | 29,67 | **40,83** | 34,80 | 39,04 | 24,12 | 23,63 | 24,04 | 25,59 | 26,65 | 5,95 |
| LongBench v2 | **44,73** | 42,54 | 32,80 | 34,00 | 30,22 | 37,18 | 24,65 | 9,15 | 0,00 | 0,00 |
| OAB-Bench · 210 · completo | **73,94** | 45,24 | 49,43 | 52,34 | 46,86 | 24,92 | 32,71 | 24,06 | 15,39 | 3,52 |
| Magis-Bench · 74 · completo | **41,10** | 17,32 | 22,56 | 22,15 | 14,40 | 4,93 | 8,31 | 4,62 | 2,07 | 0,33 |
| CondutaBench · 140 | **77,00** | 50,93 | 49,39 | 53,58 | 28,96 | 25,85 | 34,93 | 19,59 | 17,64 | -3,16 |

</details>

[Explorar os registros finais](results/README.md) · [Conferir notas e médias](verifier/README.md)

<!-- END VERIFIED RESULTS -->

## Organização

| Pasta | Conteúdo |
|---|---|
| [results](results/README.md) | Respostas, julgamentos, parâmetros, tokens, custos e notas finais. |
| [benchmarks](benchmarks/README.md) | 22 implementações utilizadas, com fontes, revisões, protocolos e adaptações. |
| [profiles](profiles/README.md) | Perfis de cada modelo e modo, protocolos dos juízes e matriz de execução. |
| [envs](envs/README.md) | Dependências e versões fixadas de cada ambiente. |
| [verifier](verifier/README.md) | Conferência local das notas, médias, cobertura e rankings do Observatório. |
| [observatory](observatory/README.md) | Interface interativa e build estático a partir dos resultados finais. |

```text
results/
  s5-nano/
    capitu/
      thinking/
        resumo.json
        respostas-0001.json
      instruct/
        resumo.json
        respostas-0001.json
benchmarks/<categoria>/<benchmark>/fork/
profiles/models/<modelo>/
profiles/judges/
envs/
verifier/
run_all.sh
```

Para conferir o que está reportado, sem acessar APIs ou o Observatório:

```bash
python -m pip install -r envs/requirements.txt
python -m verifier
```

Para ver a matriz completa de reprodução, sem iniciar nenhuma chamada:

```bash
./run_all.sh --plan
```

São 390 execuções que produzem os 426 conjuntos: MMLU PT gera duas métricas,
e CAPITU gera as métricas de instruções e conversas. Thinking vem primeiro;
Instruct usa o próprio perfil. Combinações sem suporte não são executadas.

A preparação dos servidores, das dependências e dos acessos aos juízes está em
[profiles/README.md](profiles/README.md). O comando de execução é:

```bash
./run_all.sh --endpoints .runs/endpoints.json
```

A saída padrão é `results/`. Resultados finais existentes são verificados e
reutilizados. Para uma repetição independente, use `--output .runs/nova/results
--work .runs/nova/native`. A execução não altera as notas da referência do
Observatório. Um erro interrompe o comando e conserva os arquivos de diagnóstico;
não há repetição ilimitada de chamadas com resultado incerto.

Os resultados guardam o que foi recuperado das execuções selecionadas. Campos
não registrados são `null`; estimativas de custo são identificadas. Custos de GPU
e tentativas descartadas não compõem os custos dos registros finais.

## Citação

```bibtex

```
