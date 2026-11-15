"""Langfuse tracing when keys are set, a no-op otherwise, so the pipeline runs either way."""
import contextvars
import os
from concurrent.futures import ThreadPoolExecutor

ENABLED = bool(os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"))

if ENABLED:
    from langfuse import get_client, observe, propagate_attributes  # noqa: F401
else:
    import contextlib

    def observe(func=None, **_kw):
        if func is None:
            return lambda f: f
        return func

    def propagate_attributes(**_kw):
        return contextlib.nullcontext()


def client():
    return get_client() if ENABLED else None


def update_generation(**kw):
    if ENABLED:
        get_client().update_current_generation(**kw)


def update_span(**kw):
    if ENABLED:
        get_client().update_current_span(**kw)


def score_trace(name, value, comment=None):
    if ENABLED:
        get_client().score_current_trace(name=name, value=value, comment=comment)


def trace_url():
    if ENABLED:
        try:
            return get_client().get_trace_url()
        except Exception:
            return None
    return None


def flush():
    if ENABLED:
        get_client().flush()


def pmap(fn, items, workers):
    """Thread map that keeps the tracing context, so child calls nest under the current span."""
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(contextvars.copy_context().run, fn, it) for it in items]
        return [f.result() for f in futs]
