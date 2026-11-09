# Implementação e protocolo

O diretório `fork/` contém o runner autocontido utilizado por esta integração.
O dataset e os critérios não são reescritos. Fontes públicas, hashes e diferenças
metodológicas estão no manifesto e no protocolo.

A camada de execução usa credenciais por ambiente, recibos para retomada e
endpoints compatíveis com OpenAI. Pesquisa Serper e juiz S5 são escolhas
explícitas desta implementação. Não se afirma equivalência ao leaderboard dos
autores. Configurações distintas devem permanecer identificadas separadamente.

Os runners não incluem datasets, respostas nem julgamentos pré-executados.

Na retomada, somente recibos de julgamento que passam pela validação completa
podem ser selecionados. Tentativas inválidas são preservadas, e veredictos válidos
são reutilizados. A recuperação de uma resposta final truncada também exige o
modelo solicitado e o mesmo teto de saída. Prompts, rubricas e cálculo não mudam.
