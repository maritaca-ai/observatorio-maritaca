# Implementação e protocolo

O diretório `fork/` contém o runner autocontido utilizado por esta integração.
O dataset e os critérios não são reescritos. Fontes públicas, hashes e diferenças
metodológicas estão no manifesto e no protocolo.

A camada de execução usa credenciais por ambiente, recibos para retomada e
endpoints compatíveis com OpenAI. Pesquisa Serper e juiz S5 são escolhas
explícitas desta implementação. Não se afirma equivalência ao leaderboard dos
autores. Configurações distintas devem permanecer identificadas separadamente.

Os runners não incluem datasets, respostas nem julgamentos pré-executados.
