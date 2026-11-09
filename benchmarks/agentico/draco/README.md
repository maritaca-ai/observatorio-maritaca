# DRACO

100 perguntas e 3.934 critérios do [dataset público](https://huggingface.co/datasets/perplexity-ai/draco).
O dataset e o prompt do juiz são verificados por SHA-256 antes das chamadas.
Fontes: [manifesto](fork/dataset_manifest.json), [protocolo](protocol.json) e
[artigo](https://arxiv.org/abs/2602.11685).

Cada critério recebe `MET` ou `UNMET`. A nota por pergunta é
`100 × clamp(Σ peso × veredicto / Σ pesos positivos, 0, 1)`; a nota final é
a média das 100 perguntas. Critérios negativos preservam seu significado.
Uma avaliação incompleta não recebe nota agregada completa.

O `run.sh` usa pesquisa Serper e juiz S5 Instruct (`reasoning_effort=none`).
São 30 chamadas de ferramenta, leitura em blocos de 10.000 caracteres e busca
com localização Brasil. Um julgamento por critério. O agente de pesquisa e a
escolha do juiz são configurações desta implementação, não uma reprodução do
leaderboard dos autores. Os prompts e o cálculo estão preservados.

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
# Geração. Ajuste modelo, URL e limite de saída ao endpoint servido.
./benchmarks/agentico/draco/run.sh \
  --phase generate --run-id modelo-draco --model nome-servido \
  --provider openai --base-url http://localhost:8000/v1 \
  --api-key-env CANDIDATE_API_KEY --reasoning-effort none \
  --max-tokens 32768 --workers 4

# Julgar as respostas salvas, sem repetir a geração.
./benchmarks/agentico/draco/run.sh --phase judge --run-id modelo-draco

# Consolidar offline.
./benchmarks/agentico/draco/run.sh --phase score --run-id modelo-draco
```

`--phase all` executa geração e julgamento. `--phase import --responses arquivo.jsonl`
aceita relatórios externos com `case_id`, `generator` e `text`, preservando sua
origem; eles permanecem identificados como importados. Também estão disponíveis
os providers `maritaca` e `openrouter`. O CLI interno mantém pesquisa nativa e
juiz `xhigh` como defaults; o `run.sh` explicita Serper/S5 Instruct. A pesquisa
nativa só é oferecida pelos providers que a suportam.

O runner DRACO não aplica o redutor de contexto do ResearchRubrics. Respostas
interrompidas por limite podem provocar aumento do teto na tentativa técnica,
como registrado nos recibos; avalie esse comportamento ao configurar modelos
com janela pequena. Ele não é equivalente a uma execução com teto fixo.

A opção `--selection per-domain` é diagnóstica e não substitui as 100 perguntas.
A comparação entre juízes (`--phase compare`) exige as mesmas respostas e
configurações identificadas por `--judge-label`.

No W&B, DRACO publica resumo e configuração, não os arquivos completos dos
recibos. O JSON local usa escala **0–100**; a métrica `draco/score` do W&B usa
**0–1**, preservando o contrato do runner. Configurações de pesquisa/juiz distintas
recebem identificadores distintos; não devem ser agregadas como equivalentes.
