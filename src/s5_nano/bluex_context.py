"""Preserve native BLUEX failed-generation scoring for typed context rejection."""
from .context_failures import is_context_limit_response


def generate(client, model, question, subquestion, prompt, context_length):
    common = dict(question=question, sub=subquestion, prompt=prompt)
    try:
        response = client.chat.completions.create(model=model,
            messages=[{'role': 'user', 'content': prompt}], temperature=1)
    except Exception as exc:
        body = getattr(exc, 'body', None)
        if not is_context_limit_response(getattr(exc, 'status_code', None), body, context_length):
            raise
        return dict(common, response=None, finish_reason=None, error='model_context_exhausted',
                    model_context_exhausted=True, raw_error=body)
    choice = response.choices[0]
    return dict(common, response=choice.message.content or '', finish_reason=choice.finish_reason,
                error=None, raw=response.model_dump(mode='json'))
