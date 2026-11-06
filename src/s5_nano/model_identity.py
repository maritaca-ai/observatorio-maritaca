"""Fail-closed response identity shared by SDK clients and direct canaries."""
from pathlib import Path
from contextlib import contextmanager
from contextvars import ContextVar
import time
import uuid


class ModelIdentityError(ValueError):
    """A completed response needs audit, never an automatic retry."""


# Explicit native OAB mapping. No prefix matching or discovered alias fallback.
OPENAI_RESPONSE_ALIASES = {'gpt-5.2': frozenset({'gpt-5.2-2025-12-11'})}
_VALIDATIONS = ContextVar('response_model_validations', default=None)


@contextmanager
def capture_model_validations():
    values = []
    token = _VALIDATIONS.set(values)
    try:
        yield values
    finally:
        _VALIDATIONS.reset(token)


def expected_model(request, extra=None):
    model = request.get('model') if isinstance(request, dict) else None
    if not isinstance(model, str) or not model.strip():
        raise ModelIdentityError('An explicit request model is required before dispatch')
    if extra is not None and (not isinstance(extra, dict) or extra.get('model', model) != model):
        raise ModelIdentityError('Extra request body cannot replace the explicit model')
    return model


def verify_response_model(raw, expected, root, *, source, request=None, provider_host=None):
    returned = raw.get('model') if isinstance(raw, dict) else None
    allowed = OPENAI_RESPONSE_ALIASES.get(expected, ()) if provider_host == 'api.openai.com' else ()
    if isinstance(returned, str) and (returned == expected or returned in allowed):
        values = _VALIDATIONS.get()
        if values is not None:
            values.append(dict(expected_model=expected, returned_model=returned, provider_host=provider_host))
        return
    from .auditing import append, store
    identifier = uuid.uuid4().hex
    record = dict(time=time.time(), expected_model=expected, returned_model=returned,
                  source=source, status='MODEL_IDENTITY_AUDIT_REQUIRED', retry_allowed=False)
    artifact = store(Path(root), identifier, 'model_identity_error', dict(record, raw=raw, request=request))
    append(Path(root) / 'model_identity_errors.jsonl', dict(record, **artifact))
    raise ModelIdentityError('Response model is missing or differs; preserved for audit')
