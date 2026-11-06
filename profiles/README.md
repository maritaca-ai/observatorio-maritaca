# Protocolos de execução

[`plan.json`](plan.json) é a matriz explícita: modelo, modo, benchmark, arquivo do
perfil e pastas de resultado esperadas. Os 37 arquivos em `models/` preservam as
variantes registradas, incluindo os limites específicos para matemática. Cada
modelo tem um README com o mapa de benchmarks e as referências utilizadas.

Cada perfil contém amostragem, contexto, limite de saída, modo, template,
histórico e parsers, quando aplicáveis. `max_tokens: null` significa que não há
um teto adicional nesse perfil; o contexto disponível e as regras do benchmark
continuam aplicáveis. Os perfis distinguem recomendações dos autores das escolhas
da campanha. Alterar um perfil produz outro protocolo.

O proxy comum impõe os parâmetros do perfil no envio ao modelo. O teste inicial
confere o modo solicitado, o template renderizado e os tokens recebidos pelo
servidor. Reasoning espontâneo é preservado separadamente; a correção usa a
resposta final.

[`benchmarks.json`](benchmarks.json) fixa os recortes, sementes, fontes e juízes
dos benchmarks que precisam de seleção adicional. Os demais protocolos estão
junto aos forks. `judges/<benchmark>.json` registra os parâmetros recuperados
dos julgamentos finais, suas variantes e referências. Os campos por chamada em
`results/` permitem inspecionar a evidência detalhada. Ausência de parâmetro
registrado não significa que o provedor usou um valor conhecido.

## Preparar o ambiente

É necessário Linux, `uv` e espaço para os dados públicos. As bibliotecas estão
fixadas nos arquivos `requirements*.lock`. As instalações ficam neste checkout:

```bash
bash scripts/setup.sh
bash scripts/setup_remaining.sh
bash scripts/setup_plus.sh          # requer JAVA_HOME apontando para Java 21
bash scripts/setup_harm_scorer.sh
```

BrowseComp-Plus usa o índice BM25 e o tokenizador de trechos da implementação
original. Esse tokenizador de busca é independente do tokenizador do modelo
avaliado. Os dados são baixados nas revisões fixadas e guardados em `.cache/`.

Os modelos devem estar servidos em endpoints compatíveis com o protocolo,
com seus tokenizadores e templates locais. As versões de ambiente registradas
estão em `locks/*serving*.json`; LFM3 também tem o ambiente SGLang fixado.
O adaptador Transformers utilizado para backends compatíveis está em
`src/s5_nano/hf_server.py`. Não se presume que qualquer API de chat forneça as
evidências de tokenização exigidas pelo teste inicial.

Os templates recuperados de Gaia, Lumi, Manacá, LatamGPT e Tucano Thinking estão
em `templates/`, conferidos contra as respectivas versões dos perfis. Os demais
devem vir dos artefatos do checkpoint indicado. O campo `chat_template_sha256`
identifica o template efetivamente usado; quando houver adaptação de histórico,
não basta usar o arquivo original sem essa adaptação.

O proxy já aplica o adaptador textual de ferramentas do Gaia, preservado em
`src/s5_nano/gaia_transport_adapter.py` com a referência do Google ADK. Use o
endpoint nativo do modelo: não adicione uma segunda cópia desse adaptador.
Manacá conserva as sequências de parada e a variante explícita de representação
do system quando declarada no perfil. Tucano usa `src/s5_nano/tucano_transport.py`
sobre o servidor de completions; o adaptador verifica pesos, template e contexto
antes de aceitar chamadas. Esses tratamentos não são intercambiáveis entre modelos.

O repositório não inclui pesos nem provisiona infraestrutura. O checkpoint
textual avaliado do S5-nano precisa ser fornecido localmente por quem tem acesso;
a referência GGUF não implica que essas quantizações foram usadas na campanha.

## Configurar endpoints e executar

```bash
mkdir -p .runs
cp profiles/endpoints.example.json .runs/endpoints.json
```

Edite esse arquivo local. Há uma entrada por `modelo:modo`, usando os IDs de
`results/modelos.json`. Cada entrada precisa de `api_base`, `tokenizer` e
`chat_template`. O nome servido deve coincidir com `model` no perfil. O campo
opcional `python` escolhe o interpretador do worker daquele endpoint. Tokens de
acesso ficam apenas no ambiente, nunca nesse JSON ou no Git.

Os benchmarks com juiz utilizam `OPENAI_API_KEY`, `MARITACA_API_KEY` ou
`OPENROUTER_API_KEY`, conforme o protocolo. MARCA também requer `SERPER_API_KEY`.
Para HarmBench, configure `S5_NANO_HARM_CLASSIFIER` com os pesos do classificador,
`S5_NANO_HARM_SERVING_PYTHON` com o Python do servidor vLLM e
`S5_NANO_HARM_SCORER_PYTHON` com o Python de `.cache/harm-scorer-venv`.
Essas variáveis não têm valores incorporados ao código.

```bash
# Inspeção: sem rede, sem GPU e sem chamadas aos juízes.
./run_all.sh --plan

# Toda a matriz; verifica e reutiliza resultados finais já presentes.
./run_all.sh --endpoints .runs/endpoints.json

# Uma repetição independente de um modelo/modo/benchmark.
./run_all.sh --models s5-nano --modes thinking --benchmarks capitu \
  --endpoints .runs/endpoints.json \
  --output .runs/repeticao/results --work .runs/repeticao/native

python -m verifier --results .runs/repeticao/results --new-run
```

`--workers` controla a concorrência dentro do benchmark. A ordem dos modelos
fica explícita no plano; o comando não ocupa GPUs adicionais por conta própria.
Não se misturam respostas de modos diferentes. Uma resposta final reutilizada
não provoca nova cobrança. O código conserva falhas de transporte para inspeção
e não interpreta um timeout como autorização para repetir a chamada.

Para um limite preventivo de chamadas em USD, o mecanismo
`S5_NANO_JUDGE_BUDGET_FILE` aceita um JSON local com `alert_and_pause_usd` e
`reserve_per_attempt_usd`. Ele cobre OpenAI/OpenRouter, reserva chamadas ainda
sem custo conhecido e para novos envios ao atingir a reserva. Não representa
um teto de faturamento e não cobre cobranças em BRL da Maritaca. Os custos nos
arquivos finais representam somente os julgamentos selecionados.
