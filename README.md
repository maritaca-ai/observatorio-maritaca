# S5-nano

Modelo de linguagem da Maritaca AI. Este repositório permanece **privado**.

Aqui estão as avaliações finais do S5-nano e dos dez modelos comparados com ele:
**426 conjuntos, 1.079.754 respostas selecionadas e 425 notas numéricas**.
O conjunto sem capacidade demonstrada permanece sem nota. Os controles benignos
do Lumen ficam separados das respostas que compõem a taxa de dano.

<!-- BEGIN VERIFIED RESULTS -->

## Resultados

Médias e notas finais, separadas por modo. Os melhores valores de cada coluna de média ou linha de benchmark aparecem em **negrito**.

### Thinking

| Posição | Modelo | Nativo BR | Traduzido PT | Não nativo | Total | Testes |
|---:|---|---:|---:|---:|---:|---:|
| 1 | S5-nano 🇧🇷 | **83,74** | 86,94 | 54,11 | **75,25** | 23/23 |
| 2 | Qwen3.5-4B | 72,49 | **87,61** | 54,82 | 68,68 | 23/23 |
| 3 | LFM2.5-24B-A2B | 69,68 | 87,30 | **56,45** | 67,06 | 23/23 |
| 4 | Nemotron 3.5 Bolt E4B | 71,42 | 84,92 | 50,78 | 64,95 | 23/23 |
| 5 | Gemma 4 E4B | 71,64 | 83,82 | 47,22 | 63,68 | 23/23 |
| 6 | LFM3-1.7B | 57,60 | 74,76 | 50,71 | 57,94 | 23/23 |
| 7 | Lumi 4B 🇧🇷 | 52,68 | 52,50 | 33,97 | 44,77 | 23/23 |
| 8 | Tucano2-qwen-3.7B 🇧🇷 | 34,83 | 46,12 | 30,45 | 33,13 | 22/23 |

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
| 1 | S5-nano 🇧🇷 | **74,65** | 83,48 | 44,06 | **66,51** | 23/23 |
| 2 | Qwen3.5-4B | 66,22 | **84,94** | **47,20** | 61,84 | 23/23 |
| 3 | Nemotron 3.5 Bolt E4B | 67,58 | 81,16 | 46,57 | 60,47 | 23/23 |
| 4 | Gemma 4 E4B | 68,10 | 77,91 | 44,61 | 59,93 | 23/23 |
| 5 | LatamGPT 70B | 47,66 | 66,97 | 42,99 | 48,19 | 20/23 |
| 6 | Gaia 4B 🇧🇷 | 46,25 | 66,90 | 34,95 | 43,26 | 23/23 |
| 7 | LFM3-1.7B | 47,17 | 11,57 | 39,33 | 42,31 | 23/23 |
| 8 | Lumi 4B 🇧🇷 | 43,40 | 59,48 | 35,16 | 40,55 | 23/23 |
| 9 | Tucano2-qwen-3.7B 🇧🇷 | 31,87 | 40,97 | 25,30 | 29,75 | 23/23 |
| 10 | Manacá 🇧🇷 | 7,01 | 27,76 | 19,56 | 12,85 | 20/23 |

<details>
<summary>Resultados por benchmark · Instruct</summary>

| Benchmark | S5-nano 🇧🇷 | Qwen3.5-4B | Nemotron 3.5 Bolt E4B | Gemma 4 E4B | LatamGPT 70B | Gaia 4B 🇧🇷 | LFM3-1.7B | Lumi 4B 🇧🇷 | Tucano2-qwen-3.7B 🇧🇷 | Manacá 🇧🇷 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Arena-Hard v2 | 4,67 | 10,01 | **19,31** | 18,47 | 3,41 | 1,00 | 2,86 | 1,45 | 0,33 | 0,00 |
| Prosa-PT | **64,70** | 57,12 | 58,11 | 58,45 | 27,89 | 42,28 | 40,00 | 35,21 | 20,44 | 7,66 |
| IFBench | 27,33 | 30,67 | **45,00** | 30,00 | 14,33 | 20,00 | 31,67 | 22,33 | 13,33 | 17,33 |
| CAPITU | 68,50 | 70,50 | 78,50 | **84,00** | 62,50 | 74,00 | 73,00 | 69,50 | 54,00 | 17,00 |
| CAPITU · conversas completas | 76,00 | 73,00 | 69,00 | **78,00** | 61,00 | 67,00 | 63,00 | 58,00 | 26,00 | 7,00 |
| Lumen PT | **99,38** | 93,52 | 97,53 | 96,37 | — | 66,36 | 83,56 | 85,65 | 61,81 | — |
| HarmBench | 85,00 | **95,00** | 92,19 | 90,31 | 88,12 | 76,25 | 87,19 | 90,31 | 83,44 | 94,06 |
| MMLU-PT · ensino médio | 70,81 | **76,84** | 72,63 | 73,73 | 42,32 | 41,61 | 48,42 | 38,52 | 1,47 | 0,97 |
| MMLU-PT · graduação | **69,66** | 59,60 | 64,40 | 65,28 | 51,57 | 43,24 | 40,62 | 38,00 | 1,48 | 0,14 |
| Global-MMLU PT | 72,96 | **75,88** | 69,66 | 61,83 | 44,71 | 46,44 | 21,83 | 38,35 | 5,62 | 12,36 |
| ENADE-QA | **71,79** | 66,48 | 64,11 | 66,34 | 57,96 | 41,48 | 40,08 | 46,79 | 44,83 | 22,49 |
| ENEM-VL · texto | **78,57** | 76,06 | 75,25 | 76,01 | 76,81 | 59,81 | 54,68 | 66,00 | 71,08 | 18,06 |
| BLUEX v2 · texto | **85,60** | 80,49 | 80,51 | 80,00 | 72,16 | 66,06 | 70,56 | 66,46 | 41,07 | 3,00 |
| MATH-PT · PT-BR | 82,29 | **84,95** | 78,68 | 83,70 | 12,07 | 27,12 | 84,64 | 27,90 | 7,52 | 0,00 |
| MARCA público | **83,86** | 61,31 | 23,96 | 25,14 | — | 15,33 | 61,37 | 3,41 | 11,02 | — |
| BrowseComp-Plus | **25,00** | 17,00 | 5,00 | 7,00 | — | 1,00 | 6,00 | 1,00 | 1,00 | — |
| Structured Output Benchmark | 92,05 | 94,32 | 96,89 | 93,44 | **97,71** | 97,69 | 86,81 | 96,31 | 52,34 | 0,00 |
| BRoverbs | 87,13 | 81,78 | **87,48** | 73,32 | 78,41 | 63,30 | 22,02 | 41,88 | 75,47 | 14,08 |
| ASSIN 2 · RTE | **94,00** | 94,00 | 92,67 | 94,00 | 89,23 | 87,36 | 1,30 | 80,60 | 76,32 | 43,17 |
| CulturalBench Hard | 29,67 | **40,83** | 34,80 | 39,04 | 24,12 | 24,04 | 23,63 | 25,59 | 26,65 | 5,95 |
| LongBench v2 | **44,73** | 42,54 | 32,80 | 34,00 | 30,22 | 24,65 | 37,18 | 9,15 | 0,00 | 0,00 |
| OAB-Bench · 210 · completo | **73,94** | 45,24 | 49,43 | 52,34 | 46,86 | 32,71 | 24,92 | 24,06 | 15,39 | 3,52 |
| Magis-Bench · 74 · completo | **41,10** | 17,32 | 22,56 | 22,15 | 14,40 | 8,31 | 4,93 | 4,62 | 2,07 | 0,33 |
| CondutaBench · 140 | **77,00** | 50,93 | 49,39 | 53,58 | 28,96 | 34,93 | 25,85 | 19,59 | 17,64 | -3,16 |

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
