# ResearchRubrics

101 perguntas e 2.593 critérios humanos do
[dataset público](https://huggingface.co/datasets/ScaleAI/researchrubrics).
O [manifesto](fork/upstream_manifest.json) fixa a revisão e os hashes do dataset
e dos quatro prompts oficiais; os downloads acontecem em cache, fora do Git.
Veja o [código oficial](https://github.com/scaleapi/researchrubrics) e o
[protocolo desta implementação](protocol.json).

O código oficial avalia relatórios já produzidos. A geração aqui é um agente
com ferramentas Serper: 30 chamadas, páginas em blocos de 10.000 caracteres e
localização Brasil. O candidato recebe a pergunta, sem as rubricas. O juiz é
S5 Instruct, com um voto binário por critério, em lugar do Gemini utilizado pelo
avaliador oficial; por isso não se afirma reprodução do leaderboard original.

A nota por pergunta é `100 × Σ peso × decisão / Σ pesos positivos` e a nota final
é a média das 101 perguntas. Pesos negativos são mantidos, **sem clipping**.
Relatórios longos seguem os prompts oficiais de extração por blocos e síntese
no julgamento. Uma execução incompleta não publica a nota agregada.

## Ambiente e credenciais

Da raiz do repositório, prepare um ambiente com Python 3.11–3.13:

```bash
uv venv --python 3.13 .venv-deep-research
uv pip install --python .venv-deep-research/bin/python -r envs/deep-research.txt
export PYTHON="$PWD/.venv-deep-research/bin/python"
```

Forneça as chaves por variáveis de ambiente, sem colocá-las no comando ou em
arquivos versionados: `CANDIDATE_API_KEY` para o endpoint avaliado,
`MARITACA_API_KEY` para o juiz S5 e `SERPER_API_KEY` para busca e leitura.
Os nomes podem ser alterados pelos parâmetros `--api-key-env`,
`--judge-api-key-env` e `--search-api-key-env`.

`--provider openai` significa um endpoint compatível com Chat Completions,
como um servidor local. Exige `--base-url` e credencial explicitamente indicada;
não usa automaticamente uma chave de outra API. `--reasoning-effort none`
omite esse campo nesse adaptador: não altera o template nem desativa o thinking
do servidor. O endpoint deve servir o ID solicitado e fornecer tool calls no
formato da API. Pesos, template e sampling devem ser configurados no serving;
os exemplos abaixo não certificam um perfil de modelo.

## Registros e retomada

Os arquivos ficam por padrão em `.runs/`, fora do Git. Respostas, pedidos,
recibos e julgamentos são preservados. Repetir o comando com o mesmo ID retoma
os resultados já salvos; mudar configurações exige outro ID. Faça apenas uma
execução por diretório. Uma chamada cujo resultado não foi recebido exige
auditoria antes de repetir: ausência de recibo não comprova ausência de cobrança.

Nenhum resultado desta integração é publicado automaticamente em `results/`,
na interface ou nas médias do Observatório. Estes runners são invocados pelos
seus próprios `run.sh`; a matriz histórica de `run_all.sh` permanece igual.

## W&B opcional

A execução local não depende do W&B. Para usar a publicação, instale `wandb`
no mesmo ambiente e informe **ambos** `--wandb-entity SUA_CONTA` e
`--wandb-project SEU_PROJETO`, além de `--wandb`. Não há conta nem projeto
predefinidos. Os dados enviados e a escala da métrica estão descritos abaixo.

## Executar

```bash
./benchmarks/agentico/researchrubrics/run.sh \
  --phase generate --run-id modelo-rr --model nome-servido \
  --provider openai --base-url http://localhost:8000/v1 \
  --api-key-env CANDIDATE_API_KEY --reasoning-effort none \
  --context-length 131072 --max-tokens 32768 --workers 4

./benchmarks/agentico/researchrubrics/run.sh --phase judge --run-id modelo-rr
./benchmarks/agentico/researchrubrics/run.sh --phase score --run-id modelo-rr
```

`--phase all` gera e julga. Para importar relatórios, use
`--phase import --model nome-do-modelo --responses arquivo.jsonl` com registros
`case_id`, `text` e `source` opcional. Informe também o provider e esforço reais
do candidato importado, para não atribuir os defaults a respostas externas.

## Contexto e saída

A reserva adicional é configurável por `--context-reserve`, default **4096**.
O orçamento conservador em bytes é
`min(500000, context_length - max_tokens - context_reserve)` e precisa ser positivo.
Contexto 4096, saída 1024 e reserva 256 deixam 2816 bytes; esse exemplo ilustra
a conta e não garante que uma pesquisa completa caiba no modelo.

O agente preserva pergunta e raciocínio e reduz trechos antigos de fontes quando
necessário; as fontes completas continuam nos recibos. Se o restante ainda não
couber, registra a falha. Uma resposta visível interrompida no teto configurado
é mantida com `output_limit_reached`, sem regenerar para melhorar sua qualidade.

No W&B, a nota usa escala **0–100**. O upload inclui configuração, respostas,
julgamentos e recibos completos. Revise os artefatos antes de habilitar o envio;
eles podem conter URLs do serving e material recuperado da web.

## Atribuição

Dataset e prompts: Scale AI, ResearchRubrics. Licença MIT; veja
[LICENSE.upstream](LICENSE.upstream). Esta implementação compartilha transporte
e ferramentas com o [DRACO](../draco/README.md), sem depender de outro repositório.
