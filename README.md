# S5-nano

Modelo de linguagem da Maritaca AI. Este repositório permanece **privado**.

Aqui estão as avaliações finais do S5-nano e dos dez modelos comparados com ele:
**426 conjuntos, 1.079.754 respostas selecionadas e 425 notas numéricas**.
O conjunto sem capacidade demonstrada permanece sem nota. Os controles benignos
do Lumen ficam separados das respostas que compõem a taxa de dano.

| Pasta | Conteúdo |
|---|---|
| [results](results/README.md) | Respostas, julgamentos, parâmetros, tokens, custos e notas finais. |
| [benchmarks](benchmarks/README.md) | 22 implementações utilizadas, com fontes, revisões, protocolos e adaptações. |
| [profiles](profiles/README.md) | Perfis de cada modelo e modo, protocolos dos juízes e matriz de execução. |
| [verifier](verifier/README.md) | Conferência local das notas, médias, cobertura e rankings do Observatório. |

```text
results/
  s5-nano/
    capitu/
      thinking/
        resumo.json
        respostas-0001.json
      instruct/
        resumo.json
        respostas-0001.json
benchmarks/<categoria>/<benchmark>/fork/
profiles/models/<modelo>/
profiles/judges/
verifier/
run_all.sh
```

Para conferir o que está reportado, sem acessar APIs ou o Observatório:

```bash
python -m pip install -r requirements.txt
python -m verifier
```

Para ver a matriz completa de reprodução, sem iniciar nenhuma chamada:

```bash
./run_all.sh --plan
```

São 390 execuções que produzem os 426 conjuntos: MMLU PT gera duas métricas,
e CAPITU gera as métricas de instruções e conversas. Thinking vem primeiro;
Instruct usa o próprio perfil. Combinações sem suporte não são executadas.

A preparação dos servidores, das dependências e dos acessos aos juízes está em
[profiles/README.md](profiles/README.md). O comando de execução é:

```bash
./run_all.sh --endpoints .runs/endpoints.json
```

A saída padrão é `results/`. Resultados finais existentes são verificados e
reutilizados. Para uma repetição independente, use `--output .runs/nova/results
--work .runs/nova/native`. A execução não altera as notas da referência do
Observatório. Um erro interrompe o comando e conserva os arquivos de diagnóstico;
não há repetição ilimitada de chamadas com resultado incerto.

Os resultados guardam o que foi recuperado das execuções selecionadas. Campos
não registrados são `null`; estimativas de custo são identificadas. Custos de GPU
e tentativas descartadas não compõem os custos dos registros finais.
