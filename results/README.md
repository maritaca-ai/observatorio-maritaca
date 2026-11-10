# Resultados das avaliações

## Modelos

- [S5-nano](s5-nano/README.md)
- [Qwen3.5-4B](qwen3.5-4b/README.md)
- [Gemma 4 E4B](gemma-4-e4b/README.md)
- [Nemotron 3.5 Bolt E4B](nemotron-3.5-bolt-e4b/README.md)
- [LFM3-1.7B](lfm3-1.7b/README.md)
- [LFM2.5-24B-A2B](lfm2.5-24b-a2b/README.md)
- [Gaia 4B](gaia-4b/README.md)
- [Manacá](manaca/README.md)
- [Tucano2-qwen-3.7B](tucano2-qwen-3.7b/README.md)
- [Lumi 4B](lumi-4b/README.md)
- [LatamGPT 70B](latamgpt-70b/README.md)

## Arquivos

Cada modelo tem uma pasta. Dentro dela, os benchmarks ficam separados por modo:

```text
results/
  s5-nano/
    bluex-v2/
      instruct/
        README.md
        resumo.json
        respostas-0001.json
      thinking/
        README.md
        resumo.json
        respostas-0001.json
```

`README.md` mostra a nota e oferece links para as respostas. `resumo.json`
descreve a população avaliada, a agregação da nota e a cobertura dos metadados.
Os arquivos `respostas-*.json` usam JSON formatado e têm lotes pequenos para
leitura no GitHub. A ordem dos campos é a mesma em todos os benchmarks.

| Campo | Conteúdo |
| --- | --- |
| `id` | Identificador legível do exemplo dentro do benchmark. |
| `system` | Mensagem de sistema registrada. `""` indica ausência explícita; `null`, registro indisponível. |
| `pergunta` | Pergunta ou instrução apresentada ao modelo. |
| `resposta` | Resposta final selecionada para a correção. |
| `parametros_inferencia` | Parâmetros registrados para gerar a resposta. A origem informa se são os valores efetivamente enviados ou o perfil da execução. |
| `total_tokens` | Tokens de entrada e saída, somados nos testes com múltiplos turnos. |
| `custo` | Custo de API da geração, com moeda e origem. Não inclui GPUs. |
| `julgamento` | Critérios, veredictos e justificativas da correção final. |
| `parametros_inferencia_julgamento` | Parâmetros da chamada ao juiz, quando há um modelo juiz. |
| `total_tokens_julgamento` | Tokens das chamadas selecionadas ao juiz. |
| `custo_julgamento` | Custo de API dos julgamentos selecionados, com moeda e origem. |
| `score` | Nota individual na escala descrita no resumo do benchmark. |

Quando disponíveis, os registros incluem também raciocínio separado da resposta,
tokens de entrada e saída, histórico da conversa, chamadas de ferramentas,
mensagens enviadas ao juiz e motivo de encerramento da geração.

`null` significa que o valor não pôde ser recuperado dos registros; não equivale
a zero. Correções determinísticas têm custo de API zero e não possuem parâmetros
de inferência. Custos estimados permanecem identificados como estimativas, na
moeda original. Os custos destes arquivos cobrem os resultados selecionados,
não o gasto histórico com tentativas descartadas.

A nota do benchmark segue sua regra de agregação. Ela não é necessariamente a
média dos `score` individuais: há pesos, grupos de questões, rubricas e métricas
como F1. Os resumos preservam essas diferenças.

Respostas e correções selecionadas entram neste diretório. Avaliações parciais
são identificadas como tais, com os casos sem nota documentados separadamente. Modos sem avaliação têm seu estado identificado, sem notas ou
respostas inventadas.

## Conferência

Execute `python scripts/validate_results.py` na raiz do repositório. O verificador usa NumPy para reproduzir o bootstrap do Arena-Hard e somente a biblioteca padrão para os demais testes. Não faz chamadas a modelos ou serviços.

## DRACO e ResearchRubrics

Os resultados destes benchmarks seguem a mesma estrutura por modelo e modo:
`results/<modelo>/draco/<modo>/` e
`results/<modelo>/researchrubrics/<modo>/`.

| Benchmark | População completa | Protocolo |
| --- | --- | --- |
| DRACO | 100 perguntas; 3.934 critérios | [Geração e julgamento](../benchmarks/agentico/draco/README.md) |
| ResearchRubrics | 101 perguntas; 2.593 critérios | [Geração e julgamento](../benchmarks/agentico/researchrubrics/README.md) |

Cada publicação deve identificar o perfil do candidato, a configuração de busca
e o juiz utilizado, além da cobertura de respostas e julgamentos. A nota agregada
segue o respectivo runner; avaliações incompletas não recebem nota completa.
As configurações de agente e juiz devem acompanhar as notas para permitir
comparações entre execuções equivalentes.

### Resultados disponíveis

| Modelo | Modo | DRACO | ResearchRubrics |
| --- | --- | ---: | ---: |
| S5-nano | Thinking | **[61,4667](s5-nano/draco/thinking/README.md)** | **[58,8541](s5-nano/researchrubrics/thinking/README.md)** |
| S5-nano | Instruct | **[60,7376](s5-nano/draco/instruct/README.md)** | **[54,0319](s5-nano/researchrubrics/instruct/README.md)** |
| Qwen3.5-4B | Thinking | [53,6341](qwen3.5-4b/draco/thinking/README.md) | [51,9996](qwen3.5-4b/researchrubrics/thinking/README.md) |
| Qwen3.5-4B | Instruct | [39,7898](qwen3.5-4b/draco/instruct/README.md) | [42,0017](qwen3.5-4b/researchrubrics/instruct/README.md) |
| Gemma 4 E4B | Thinking | [28,2579](gemma-4-e4b/draco/thinking/README.md) | [32,2481](gemma-4-e4b/researchrubrics/thinking/README.md) |
| Gemma 4 E4B | Instruct | [25,7907](gemma-4-e4b/draco/instruct/README.md) | [30,5068](gemma-4-e4b/researchrubrics/instruct/README.md) |
| Nemotron 3.5 Bolt E4B | Thinking | [28,5964](nemotron-3.5-bolt-e4b/draco/thinking/README.md) | [30,6489](nemotron-3.5-bolt-e4b/researchrubrics/thinking/README.md) |
| Nemotron 3.5 Bolt E4B | Instruct | [23,9862](nemotron-3.5-bolt-e4b/draco/instruct/README.md) | [26,4877](nemotron-3.5-bolt-e4b/researchrubrics/instruct/README.md) |
| LFM3-1.7B | Thinking | [43,3202](lfm3-1.7b/draco/thinking/README.md) | [46,4674](lfm3-1.7b/researchrubrics/thinking/README.md) |
| LFM3-1.7B | Instruct | [39,5482](lfm3-1.7b/draco/instruct/README.md) | [41,5175](lfm3-1.7b/researchrubrics/instruct/README.md) |
| LFM2.5-24B-A2B | Thinking | [35,9472](lfm2.5-24b-a2b/draco/thinking/README.md) | [41,6973](lfm2.5-24b-a2b/researchrubrics/thinking/README.md) |
| Gaia 4B | Instruct | [16,5908](gaia-4b/draco/instruct/README.md) | [23,6298](gaia-4b/researchrubrics/instruct/README.md) |
| Lumi 4B | Thinking | [10,9877](lumi-4b/draco/thinking/README.md) | [22,8944](lumi-4b/researchrubrics/thinking/README.md) |
| Lumi 4B | Instruct | [13,8604](lumi-4b/draco/instruct/README.md) | [27,2689](lumi-4b/researchrubrics/instruct/README.md) |
| Tucano2-qwen-3.7B | Thinking | [Parcial: 91/100 julgados](tucano2-qwen-3.7b/draco/thinking/README.md) | [Parcial: 88/101 julgados](tucano2-qwen-3.7b/researchrubrics/thinking/README.md) |
| Tucano2-qwen-3.7B | Instruct | [Parcial: 48/100 julgados](tucano2-qwen-3.7b/draco/instruct/README.md) | [Parcial: 58/101 julgados](tucano2-qwen-3.7b/researchrubrics/instruct/README.md) |

**Notas para o Observatório:** no DRACO, o Tucano Instruct realizou **274 buscas web**
em 87 casos e 13 leituras de páginas. O Tucano Thinking realizou **zero buscas**,
apesar das ferramentas disponíveis no prompt: respondeu diretamente.
Os 100 casos de cada modo foram tentados; os casos sem resposta pontuável não
receberam zero. As médias parciais são 2,9967 (48 respostas) e 5,1528 (91 respostas),
respectivamente, e não devem entrar como notas finais no placar.

No ResearchRubrics, os 101 casos de cada modo do Tucano foram tentados. O
Instruct concluiu **58/101** (média parcial **4,3932**) e realizou **176 buscas**;
o Thinking concluiu **88/101** (média parcial **5,7955**) e não realizou buscas.
Todos os 3.702 critérios das respostas disponíveis foram julgados. O Instruct
teve 28 interrupções pelo orçamento de **3.072 bytes do runner** e 15 saídas
limitadas a **1.024 tokens** ainda contendo chamadas de ferramentas. No Thinking,
13 saídas consumiram esse teto sem resposta final. Esses limites configurados
não comprovam esgotamento do contexto nativo de 4K; as falhas permanecem sem nota,
com evidência por caso, e as médias parciais ficam fora do ranking.

As 28 notas completas acima cobrem a população completa do respectivo benchmark.
Estes resultados adicionais ainda não integram o catálogo e as médias históricas
do Observatório. A inclusão na interface será consolidada separadamente.

Para conferir somente estes arquivos, sem carregar os demais resultados:

```bash
python scripts/validate_results.py --supplemental-only
```



### Política das novas avaliações nativas

S5-nano, Qwen3.5-4B, Gemma 4 E4B, Nemotron 3.5 Bolt E4B, LFM3-1.7B e LFM2.5-24B-A2B usam os perfis `*-deep-research.json`. Não há `reasoning_effort` no candidato; Thinking e Instruct são controlados pelo template nativo. O LFM2.5 oferece apenas Thinking.

Três respostas finais vazias ao mesmo pedido encerram a pergunta com zero, dentro do denominador completo. Os registros preservam as três tentativas e distinguem essa regra de um julgamento por rubrica. Uma resposta final não vazia é julgada, inclusive se truncada; erros de transporte e do juiz precisam ser resolvidos. A regra foi aplicada a todos os modelos e modos desta campanha nativa.

O esgotamento comprovado do contexto nativo sem resposta final recebe zero no denominador completo. A prova exige encerramento `length` e uso total de tokens igual ao limite de contexto do perfil; um erro HTTP ou um limite menor de saída não basta.

Os perfis dos juízes estão em [DRACO](../profiles/judges/draco.json) e [ResearchRubrics](../profiles/judges/researchrubrics.json). Cada chamada selecionada registra seus parâmetros, tokens, resposta do juiz e veredito.
