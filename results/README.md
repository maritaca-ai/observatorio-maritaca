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

Somente respostas e correções selecionadas para os resultados finais entram
neste diretório. Modos sem avaliação têm seu estado identificado, sem notas ou
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
| --- | --- | --- | --- |
| CEIA-UFG/Gemma-3-Gaia-PT-BR-4b-it | Instruct | [16,5908](gaia-4b/draco/instruct/README.md) | [23,6298](gaia-4b/researchrubrics/instruct/README.md) |
| ceia-br/lumi-4b | Instruct | [13,8604](lumi-4b/draco/instruct/README.md) | [27,2689](lumi-4b/researchrubrics/instruct/README.md) |
| ceia-br/lumi-4b | Thinking | Sem nota completa | [22,8944](lumi-4b/researchrubrics/thinking/README.md) |

As cinco notas acima cobrem a população completa do respectivo benchmark.
Estes resultados adicionais ainda não integram o catálogo e as médias históricas
do Observatório. A inclusão na interface será consolidada separadamente.

Para conferir somente estes arquivos, sem carregar os demais resultados:

```bash
python scripts/validate_results.py --supplemental-only
```
