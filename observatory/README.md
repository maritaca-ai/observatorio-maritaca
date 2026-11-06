# Observatório Maritaca

Interface estática para explorar as avaliações finais: céu interativo, médias,
ranking, resultados por benchmark, comparação de respostas e escolha às cegas.
Os votos ficam apenas no navegador. Não há chamadas a modelos ou juízes.

## Construção local

Na raiz do repositório:

```bash
python -m pip install -r envs/requirements.txt
python observatory/build.py --output .runs/observatory
python -m http.server 8080 --bind 127.0.0.1 --directory .runs/observatory
```

Abra `http://127.0.0.1:8080`. Use uma pasta de saída vazia. O build lê todos os
conjuntos finais em `results/`, refaz as notas com `verifier/` e confere as médias
e posições com `verifier/reported.json`. Divergências interrompem a construção.
Não é necessário acessar APIs, servidores de inferência ou arquivos de outra
campanha.

O site inclui as respostas finais e correções selecionadas dos 11 modelos.
Entradas extensas e conversas de ferramentas são carregadas sob demanda. No
LongBench, trechos idênticos de entradas de uma mesma questão são armazenados uma
vez; o navegador reconstrói os bytes exatos de cada entrada e confere sua
integridade antes de exibi-la. Isso não altera a truncagem usada na avaliação. Os
registros completos, incluindo reasoning quando registrado, permanecem em
`results/`; cada resposta tem um link para seu arquivo de origem. Respostas a
perguntas diferentes não são pareadas apenas por terem o mesmo índice numérico.
Nenhuma pergunta é amostrada para reduzir o pacote.

Para repetir a construção, `--cache .runs/observatory-anterior` reutiliza a
compressão anterior somente após verificar o conteúdo de cada arquivo. Todas as
notas e respostas são lidas e conferidas novamente; a saída continua sendo uma
pasta vazia, sem arquivos remanescentes de outra versão.

`catalog.json` preserva os textos, referências e anotações da interface, com um
dicionário compartilhado para evitar repetir os mesmos metadados de auditoria. Não é
fonte das notas principais: elas vêm de `resumo.json` e são conferidas contra os
julgamentos. `build.json`, na saída, registra cobertura, tamanho e ausência de
chamadas externas. Arquivos gerados não devem ser commitados.

## GitHub Pages

O arquivo [pages.workflow.yml](pages.workflow.yml) contém a configuração pronta
para revisão. Ainda não é um workflow ativo: a credencial de envio atual não tem
a permissão GitHub `workflow`. Quando a publicação estiver autorizada, uma pessoa
com essa permissão deve copiá-lo para `.github/workflows/observatory-pages.yml`.

O workflow é manual, aceita apenas `main` e exige a variável de repositório
`OBSERVATORY_PAGES_AUDIENCE` com valor `public` ou `private`. Sem essa variável,
nada é publicado. Fazer push ou merge também não publica.

**Repositório privado não significa site privado.** No plano GitHub Team,
o Pages de um repositório privado é público. Controle de acesso privado ao Pages
exige Enterprise Cloud. A variável só deve ser definida após autorização explícita
da responsável para a audiência escolhida. [Visibilidade no GitHub Pages](https://docs.github.com/en/enterprise-cloud%40latest/pages/getting-started-with-github-pages/changing-the-visibility-of-your-github-pages-site).

Após essa autorização, configure Pages com a origem **GitHub Actions** e a
visibilidade aprovada, defina a variável e execute o workflow em `main`. O job
confere a visibilidade real antes de montar o artefato e nunca habilita Pages
automaticamente. O ambiente `github-pages` pode ter as proteções da organização.

O checkout do workflow contém o código e os metadados. As respostas são lidas
diretamente dos objetos Git (`--from-git`), sem copiar os 16 GB para a árvore de
trabalho. Apenas o diretório estático vai ao Pages. O build recusa um artefato
acima de 1 GB e nunca resolve esse limite omitindo casos silenciosamente.

## Verificação da interface

```bash
python -m unittest discover -s observatory/tests -p 'test_*.py'
node --test observatory/tests/case-performance.test.cjs
node observatory/tests/verify-averages.cjs .runs/observatory/data.json
python observatory/tests/browser.py --url http://127.0.0.1:8080
```

O último comando usa Playwright e uma instalação local do Chrome; dependências
opcionais em `envs/requirements-observatory-qa.txt`. Verifica rankings e médias em
todos os 66 recortes, filtros, respostas, comparação às cegas, erros de rede e
layout móvel, sem enviar dados externos.

Para desenvolvimento rápido, `--benchmarks capitu conduta_bench` monta somente
esses casos. Essa opção é exclusiva de QA; o workflow publica sempre o conjunto
completo. Fontes e imagens estão em [assets](assets/ASSETS.md).
