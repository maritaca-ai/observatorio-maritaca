# Conferir as notas do Observatório

Na raiz do repositório:

```bash
python -m pip install -r envs/requirements.txt
python -m verifier
python -m verifier --output .runs/verificacao.json
```

A verificação é local. Não lê o site, não baixa dados, não consulta modelos e não
usa credenciais. Depois de instalar as dependências, funciona sem internet.

O programa lê as respostas e os vereditos em `results/`, confere a pontuação
individual, recalcula os agregados e compara com `resumo.json` e
[`reported.json`](reported.json). Esse último arquivo conserva as notas finais e
os cálculos do Observatório; não é usado como entrada para calcular as notas.
As populações esperadas também ficam fixadas nessa referência: remover respostas
e reduzir o contador no resumo não transforma uma execução incompleta em válida.

Também confere as quatro médias — nativo brasileiro, traduzido para português,
internacional e total — e o ranking, em 66 combinações de categoria, tamanho e
modo. As contas usam precisão completa; a comparação aceita diferença absoluta
de até `1e-8` por arredondamento numérico. Um erro encerra o comando com código 1.

As regras estão em [`scores.py`](scores.py) e [`verify.py`](verify.py):

- Thinking e Instruct são linhas distintas; cada métrica primária tem peso igual.
- CAPITU conversas é complementar e não recebe peso adicional na média.
- ASSIN usa F1 macro; CulturalBench Hard exige as quatro opções corretas;
  Structured Output Benchmark usa os pesos de dificuldade dos exemplos textuais.
- Arena-Hard reproduz as duas ordens, o peso das preferências fortes e o bootstrap
  nativo, com semente 42 e 100 amostragens.
- Prosa usa as rubricas elegíveis com veredito válido, incluindo os zeros por
  contexto previstos no protocolo. OAB e MAGIS somam os pontos por exame/seção.
- BrowseComp-Plus inclui as 100 perguntas no denominador. Segurança já está na
  direção «maior é melhor»; não se aplica `100 − dano` duas vezes.
- Os 22 controles benignos por execução do Lumen estão em
  `controles-capacidade.json`. Nenhum sucesso implica ausência de nota de segurança.
- Ausência de avaliação permanece sem nota. Médias parciais têm sua cobertura
  registrada e são ranqueadas como no Observatório.

O verificador confere a aritmética dos julgamentos salvos. Não demonstra que um
juiz de linguagem julgou corretamente o conteúdo; as respostas e correções estão
disponíveis para essa inspeção. Custos não recuperados continuam `null`.

Para uma nova execução, use `python -m verifier --results CAMINHO --new-run`:
isso confere os arquivos e recalcula as médias sem exigir os mesmos valores da
campanha histórica. Não altera a referência reportada.

Testes de regressão, sem chamadas a modelos:

```bash
python -m unittest discover -s verifier/tests -v
```

Após conferir os resultados, atualize somente as tabelas do README com:

```bash
python -m verifier.export_readme
python -m verifier.export_readme --check
```

As tabelas usam `reported.json`, mantêm Thinking e Instruct separados e ordenam
pela média total. O restante do README, inclusive o espaço de citação, é
preservado. `--check` apenas confere se as tabelas estão atualizadas.

Os resultados adicionais de DRACO e ResearchRubrics podem ser conferidos com
`python scripts/validate_results.py --supplemental-only`. O verificador mantém
os pesos negativos e aplica o limite de pontuação por pergunta somente no DRACO.
Quando a campanha atribui zero após três respostas finais vazias, exige as três
tentativas concluídas, o mesmo pedido e ausência de vereditos fictícios. Esses
casos continuam no denominador; os critérios pontuados pela política ficam
separados dos critérios julgados por IA no resumo. Os resultados parciais do
Tucano continuam sem nota final e não entram nas médias históricas.

Um zero por contexto nativo exige uma resposta encerrada por `length`, sem
conteúdo final, com a soma dos tokens de entrada e saída igual ao limite nativo
do perfil. Um erro de transporte ou um teto menor de saída não satisfaz essa
condição. Respostas finais não vazias continuam sendo julgadas.
