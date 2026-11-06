"""Answer extraction for the explicitly named chat adapters.

These rules are not a replacement for native likelihood scoring.
"""
import re


def extract_answer(task, text):
    alphabet = 'ABCD' if task == 'global_mmlu_pt' else 'ABCDEFGHIJ'
    # Require a complete answer line: a Portuguese article is not an option.
    choice = rf'(?:([{alphabet}])|\(([{alphabet}])\))'
    labeled = rf'^[ \t]*(?:Resposta|Answer)[ \t]*:[ \t]*{choice}[. \t]*$'
    matches = re.findall(labeled, text, re.IGNORECASE | re.MULTILINE)
    answers = {next(x for x in match if x).upper() for match in matches}
    if len(answers) == 1:
        return answers.pop()
    if answers:
        return None  # Conflicting declarations are not silently resolved.
    match = re.fullmatch(rf'\s*{choice}[.\s]*', text, re.IGNORECASE)
    return next(x for x in match.groups() if x).upper() if match else None
