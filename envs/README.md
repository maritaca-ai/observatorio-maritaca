# Ambientes e dependências

Os benchmarks usam bibliotecas e versões diferentes. Estes arquivos permitem
reconstruir cada ambiente com as versões registradas na avaliação.

- `.in`: dependências principais escolhidas para o ambiente.
- `.lock`: versões fixadas, incluindo dependências transitivas. Os locks gerados
  com `uv` também incluem hashes dos pacotes. O arquivo de SGLang registra as
  versões instaladas no servidor, sem hashes.
- `requirements.txt`: dependência mínima para conferir os resultados com o verificador.

| Arquivos | Finalidade | Preparação, a partir da raiz |
|---|---|---|
| `requirements.txt` | Verificador de notas, médias e rankings; somente NumPy. | `python -m pip install -r envs/requirements.txt` |
| `requirements.in` e `requirements.lock` | Ambiente principal dos executores. | `bash scripts/setup.sh` |
| `requirements-scorer.in` e `.lock` | Corretores com dependências linguísticas próprias. | Criado por `scripts/setup.sh`. |
| `requirements-plus.in` e `.lock` | BrowseComp-Plus e sua busca BM25; Python 3.10 e Java 21. | `bash scripts/setup_plus.sh` |
| `requirements-remaining.in` e `.lock` | Dependências adicionais, como as usadas pelo IFBench e pelo Structured Output Benchmark. | `bash scripts/setup_remaining.sh` |
| `requirements-harm-scorer.in` e `.lock` | Correção do HarmBench. | `bash scripts/setup_harm_scorer.sh` |
| `requirements-sglang-lfm3.lock` | Versões do servidor SGLang utilizado com LFM3. | Consulte os [protocolos dos modelos](../profiles/README.md). |

Os scripts instalam os ambientes em `.venv/` ou `.cache/`. A pasta `envs/`
contém somente as definições de dependências.

Os comandos de geração registrados no cabeçalho dos locks são relativos a esta
pasta. Regerar um lock pode alterar a receita de avaliação; para reproduzir a
campanha, use os arquivos fixados e os scripts de preparação.
