"""Judge prompt for BLUEX v2, copied verbatim from the paper's code.

Source: TropicAI-Research/BLUEX-V2 @ 6c71ada8e225d6abb5dc0f90e03852c6eae3e945,
Evaluation/evaluate_model_answers.py (judge prompt v4; the paper reports 89.5%
agreement with human reviewer 1). Do not edit: scores stop being comparable.
"""

JUDGE_INSTRUCTIONS = 'Você é um especialista em correção de provas discursivas de vestibular (UNICAMP/USP). Avalie cada critério da rúbrica de forma binária (true/false) verificando se o conteúdo específico exigido está presente na resposta. Retorne somente JSON válido.'

EVALUATION_SCHEMA = {'type': 'object',
 'properties': {'criteria_checks': {'type': 'array',
                                    'items': {'type': 'object',
                                              'properties': {'criterion': {'type': 'string'},
                                                             'is_met': {'type': 'boolean'},
                                                             'justification': {'type': 'string'}},
                                              'required': ['criterion',
                                                           'is_met',
                                                           'justification'],
                                              'additionalProperties': False}},
                'overall_comment': {'type': 'string'}},
 'required': ['criteria_checks', 'overall_comment'],
 'additionalProperties': False}


def build_evaluation_prompt(
    question_text: str,
    subquestion_label: str,
    subquestion_text: str,
    expected_answer: str,
    criteria_list: list[str],
    model_name: str,
    student_answer: str,
) -> str:
    criteria_lines = "\n".join(
        f"{idx + 1}. {criterion}" for idx, criterion in enumerate(criteria_list)
    )

    return (
        "Você é corretor sênior de provas discursivas (UNICAMP/USP). Avalie cada critério da rúbrica\n"
        "decidindo se a resposta do aluno cumpre o critério, com base no GABARITO como referência.\n\n"
        "REGRA DE OURO: a rúbrica codifica IDEIAS, não palavras-chave. Sua missão é checar se a IDEIA\n"
        "está na resposta — não se as palavras estão. Sempre que o aluno expressa o conteúdo do critério\n"
        "com palavras diferentes, marque is_met=true.\n\n"
        "PRINCÍPIO 1 — PARÁFRASE E SINONÍMIA SÃO ACEITAS.\n"
        "Mesma ideia + palavras diferentes = is_met=true. Não exija termos técnicos do gabarito.\n"
        "  Ex.: critério 'fenômeno climático extremo' ↔ resposta 'evento climático severo' = ACEITO;\n"
        "  critério 'caráter sazonal' ↔ 'ocorre em períodos específicos do ano' = ACEITO.\n\n"
        "PRINCÍPIO 2 — INSTÂNCIAS, EXEMPLOS, PROPRIEDADES E CATEGORIAS SÃO INTERCAMBIÁVEIS\n"
        "QUANDO REPRESENTAM O MESMO CONTEÚDO.\n"
        "  • Categoria pedida → instância satisfaz. Ex.: critério 'mamífero' ↔ 'cachorro' = ACEITO;\n"
        "    critério 'metal alcalino' ↔ 'sódio' = ACEITO.\n"
        "  • Instância pedida → categoria-mais-específica também satisfaz, se cobrir o alvo.\n"
        "  • Tipologia pedida → descrição de propriedades características satisfaz. Ex.: critério\n"
        "    'liga magnética' ↔ resposta enumera 'forte atração por ímãs, contém ferro' = ACEITO.\n"
        "  • Conceito teórico pedido → descrição funcional/operacional satisfaz, e vice-versa.\n"
        "    Ex.: critério 'função declarativa' ↔ resposta 'serve para afirmar fatos' = ACEITO.\n\n"
        "PRINCÍPIO 3 — CONTEÚDO IMPLÍCITO LOGICAMENTE INEQUÍVOCO CONTA.\n"
        "Se o termo usado pelo aluno CONTÉM ou IMPLICA POR DEFINIÇÃO o conteúdo do critério, é true.\n"
        "Não vale associação remota — precisa ser implicação direta, recuperável apenas pela definição\n"
        "do termo.\n"
        "  • Quando o NOME de um processo/método/atividade JÁ INCORPORA o reagente, ingrediente,\n"
        "    instrumento ou agente, o critério referente a esse elemento está satisfeito.\n"
        "    Padrão: '<verbo>-ção/aplicação/uso de <X>' implica <X>.\n"
        "    Ex.: 'destilação do petróleo' implica petróleo como matéria-prima;\n"
        "         'corte a laser' implica laser como instrumento;\n"
        "         'manifestação operária' implica trabalhadores como agente.\n"
        "  • Listar processos/métodos cujos nomes nomeiam diferentes elementos satisfaz um critério\n"
        "    que pede a lista desses elementos. Ex.: critério pede '<elementos> A, B, C'; resposta\n"
        "    lista '<processos envolvendo A>, <processos envolvendo B>, <processos envolvendo C>'\n"
        "    onde cada processo nomeia explicitamente A/B/C — ACEITO.\n\n"
        "PRINCÍPIO 4 — VALORES NUMÉRICOS E UNIDADES EQUIVALENTES.\n"
        "ANTES de marcar false por valor numérico, FAÇA A CONVERSÃO mentalmente.\n"
        "Mesmo valor em outra unidade ou notação = is_met=true.\n"
        "  • 0,5 m ≡ 50 cm ≡ 500 mm ≡ 5 × 10⁻¹ m\n"
        "  • 2,0 kg ≡ 2000 g ≡ 2 × 10³ g\n"
        "  • 0,5 ≡ 50% ≡ 1/2\n"
        "  • 30 kJ ≡ 30 000 J ≡ 3 × 10⁴ J\n"
        "  • Notação científica × notação decimal: equivalentes.\n"
        "  • Múltiplos/submúltiplos SI: equivalentes.\n"
        "Se o valor e a grandeza coincidem após a conversão, é true.\n\n"
        "PRINCÍPIO 5 — JULGUE A IDEIA, NÃO A FORMA.\n"
        "Reordenar a apresentação, parafrasear, ou trocar exemplos do gabarito por exemplos\n"
        "equivalentes não desqualifica a resposta se o conteúdo central está presente.\n\n"
        "Marque is_met=false APENAS quando:\n"
        "  • A resposta OMITE completamente o ponto pedido (não tem como inferir);\n"
        "  • A resposta afirma o OPOSTO ou erra um valor numérico essencial;\n"
        "  • A resposta substitui o conceito por algo SEMANTICAMENTE DIFERENTE\n"
        "    (não apenas por uma forma diferente de dizê-lo).\n\n"
        "TESTE FINAL OBRIGATÓRIO antes de marcar false: pergunte-se 'um corretor humano experiente,\n"
        "vendo apenas o gabarito e a resposta, daria o ponto?'. Se a resposta tem espaço razoável\n"
        "para um sim, marque is_met=true.\n\n"
        "Não invente critérios novos. Não divida um critério em partes.\n"
        "A justificativa deve citar um TRECHO LITERAL da resposta (ou explicar qual ponto está ausente).\n\n"
        f"CONTEXTO DA QUESTÃO:\n{question_text}\n\n"
        f"SUBQUESTÃO (Item {subquestion_label}): {subquestion_text}\n\n"
        f"GABARITO (referência conceitual):\n{expected_answer}\n\n"
        f"CRITÉRIOS DA RÚBRICA:\n{criteria_lines}\n\n"
        f"RESPOSTA DO ALUNO:\n{student_answer}\n"
    )
