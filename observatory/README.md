# Observatório Maritaca

Interface estática para explorar as avaliações finais: céu interativo, médias,
ranking, resultados por benchmark, comparação de respostas e escolha às cegas.
Os votos ficam apenas no navegador. Não há chamadas a modelos ou juízes.

## Construção local

Na raiz do repositório:

```bash
python -m pip install -r envs/requirements.txt
python observatory/build.py --output .runs/observatory --max-bytes 0
python -m http.server 8080 --bind 127.0.0.1 --directory .runs/observatory
```

Em checkout esparso, uma prévia de alterações locais pode usar
`--from-git --worktree-overlay`: arquivos presentes no diretório de trabalho
prevalecem; os demais são lidos do commit atual. Isso não publica alterações.

As amostras de RealWorldQA e OCRBench aparecem na categoria **Visão** e nas
comparações de respostas, inclusive às cegas. Cada uma tem 200 questões;
as imagens originais são conferidas antes do build e carregadas somente ao
abrir o caso. Essas notas entram na média de Visão, preservando as médias
gerais de texto. Os protocolos, perfis visuais e corretores originais ficam
em `benchmarks/visao/` e `profiles/models/*/*-vision.json`.
O seletor **Texto / Visão** da página inicial mantém essas médias separadas;
Texto é o padrão. Modelos sem entrada de imagem aparecem como **Não suporta
visão**, sem nota numérica. As capacidades registradas distinguem falta de
suporte de uma avaliação ainda não executada.

A prévia local acima inclui as imagens originais. No Pages, o build usa
`--from-git`: confere os mesmos bytes e gera links para
os arquivos do repositório, fixados no commit usado no build. Assim, as imagens são
carregadas quando um caso é aberto, sem duplicá-las no pacote do Pages. O limite
padrão do pacote permanece ativo na publicação. Use `--image-source local`
para incluir as imagens mesmo ao ler resultados pelo Git.

Abra `http://127.0.0.1:8080`. Use uma pasta de saída vazia. O build lê todos os
conjuntos finais em `results/`, refaz as notas com `verifier/` e confere as médias
e posições com `verifier/reported.json`. Divergências interrompem a construção.
Não é necessário acessar APIs, servidores de inferência ou arquivos de outra
campanha.

O endereço sem parâmetro de idioma abre em português, independentemente do
idioma do navegador ou de visitas anteriores. O seletor **Português / English**
no topo mantém a escolha na URL (`?lang=pt` ou `?lang=en`), junto aos filtros e
à página aberta. A interface, descrições e explicações das notas têm tradução
local em `en.js`; não há serviço externo de tradução. Perguntas, respostas,
evidências dos juízes, registros técnicos e arquivos baixados preservam o
conteúdo original. Esses trechos usam `translate="no"` ou blocos de código.

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

O arquivo [pages.workflow.yml](pages.workflow.yml) contém a configuração de
publicação. Para instalá-la:

```bash
mkdir -p .github/workflows
cp observatory/pages.workflow.yml .github/workflows/observatory-pages.yml
```

O workflow é manual, aceita apenas `main` e exige a variável de repositório
`OBSERVATORY_PAGES_AUDIENCE` com valor `public` ou `private`. Sem essa variável,
nada é publicado. Fazer push ou merge também não publica.

Configure Pages com a origem **GitHub Actions** e a visibilidade desejada,
defina a variável e execute o workflow em `main`. O job
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
python observatory/tests/i18n.py --url http://127.0.0.1:8080
```

Os dois últimos comandos usam Playwright e uma instalação local do Chrome;
dependências opcionais em `envs/requirements-observatory-qa.txt`. `browser.py`
verifica rankings e médias nos 72 recortes, filtros, respostas, comparação às
cegas, erros de rede e layout móvel. `i18n.py` verifica o português como padrão,
a troca de idioma, navegação, filtros, layout móvel e preservação dos dados e
das evidências nos 26 benchmarks. Nenhum dos testes envia dados externos.

Para desenvolvimento rápido, `--benchmarks capitu conduta_bench` monta somente
esses casos. Essa opção é exclusiva de QA; o workflow publica sempre o conjunto
completo. Fontes e imagens estão em [assets](assets/).

A ressalva `observacao_nota` do `resumo.json`, quando presente, aparece logo abaixo
da nota no detalhe aberto ao clicar na célula. O build a projeta como `score_note`;
não é necessário expandir a seção de observações. DRACO e ResearchRubrics entram
nas médias, filtros, gráficos, metodologia, comparação de respostas e escolha às
cegas. A categoria **Deep research** reúne BrowseComp-Plus, DRACO e
ResearchRubrics; os três também pertencem a Agêntico. São filtros sobre as mesmas
notas: cada benchmark conta uma única vez na média geral. As rubricas e perguntas
precisam coincidir para parear respostas.

O build confere os 32 conjuntos desses dois benchmarks com o mesmo verificador
dos arquivos originais. Os 117 recibos de falha de geração do Tucano também
aparecem nos casos, com zero e sem simular texto de resposta ou julgamento.
Modelos sem avaliação continuam sem nota; não recebem zero. Os metadados
distinguem rubricas julgadas e critérios pontuados por política de zero.
