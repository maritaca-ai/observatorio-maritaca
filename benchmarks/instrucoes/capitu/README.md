# CAPITU

200 single-turn prompts +100 three-turn conversations; native strict checks.

O código utilizado está em `fork/`. As fontes e revisões estão em
[`upstream.lock.json`](upstream.lock.json); o protocolo está em
[`protocol.json`](protocol.json).

Execute `./run.sh --models s5-nano --modes thinking --endpoints CAMINHO`.
O adaptador comum grava `results/<modelo>/<benchmark>/<modo>/`, incluindo
respostas, parâmetros efetivos e julgamentos. `--plan` mostra os comandos sem executar.

Os resultados são conferidos por `python -m verifier`. Veja as diferenças
em [CHANGES.md](CHANGES.md).
