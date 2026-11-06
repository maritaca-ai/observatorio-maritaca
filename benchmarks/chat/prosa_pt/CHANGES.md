# Integração da saída

A implementação e os recortes usados na campanha são preservados. Os presets
explícitos de cada modelo prevalecem sobre defaults do benchmark. Somente a
resposta final recebe nota. O registro por turno conserva o reasoning separado.

A saída nativa fica no diretório de execução; `s5_nano.export_results` seleciona
os registros finais e grava o formato comum em `results/`. O exportador não
faz chamadas ao modelo nem ao juiz. A verificação aritmética ocorre antes de
promover uma pasta completa. As diferenças do protocolo estão em `protocol.json`.
