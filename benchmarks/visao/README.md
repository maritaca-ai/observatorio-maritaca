# Visão

RealWorldQA e OCRBench usam as mesmas 200 questões por modelo e modo.
As amostras foram fixadas antes da campanha, com semente `20261110`:

| Benchmark | Seleção | Correção |
|---|---|---|
| [RealWorldQA](https://huggingface.co/datasets/xai-org/RealworldQA) | 200 de 765, uniforme e sem reposição | Comparação exata e extrator de alternativas nativos |
| [OCRBench v1](https://huggingface.co/datasets/echo840/OCRBench) | 200 de 1.000, estratificadas proporcionalmente pelas categorias originais | Regras originais de reconhecimento e correspondência de texto |

Cada diretório contém `protocol.json`, `selection.json`, as imagens originais e
o corretor `upstream.py`. As revisões dos datasets e do código estão no protocolo.
As licenças do código original acompanham os arquivos. O auxiliar de extração
de alternativas em `vendor/` pertence à mesma revisão do lmms-eval usada em
RealWorldQA e segue a [licença correspondente](realworldqa/LICENSE).

`scoring.py` executa os trechos originais de correção, sem importar dependências
de geração dos autores. O verificador reaplica esses trechos às respostas finais
em `results/<modelo>/<benchmark>/<modo>/`. O reasoning fica preservado no registro,
mas não recebe nota. Não há chamadas a um juiz de IA.

Os perfis `profiles/models/*/*-vision.json` registram os parâmetros de geração,
o processamento visual e os limites efetivos. Resposta final vazia após três
tentativas recebe zero e permanece no denominador; erros de infraestrutura não
são convertidos em erros do modelo.

O Observatório identifica estas avaliações como amostras e as mantém fora das
médias gerais de texto. A média de Visão usa os dois benchmarks, com peso igual.
Modelos sem suporte a imagens permanecem sem nota numérica.
