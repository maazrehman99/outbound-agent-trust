"""One structured model call through the LiteLLM proxy, traced as a Langfuse generation.

The proxy speaks the OpenAI chat API, so the code is the same for any provider. Structured output
is a JSON schema built from a Pydantic model; reasoning depth is `reasoning_effort` (LiteLLM maps it,
e.g. to adaptive thinking + effort on Claude 5.5). No temperature: some current models reject it.
"""
import time

import openai

from . import config, tracing

_client = None


def client():
    global _client
    if _client is None:
        _client = openai.OpenAI(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY or "none",
                                max_retries=4, timeout=600)
    return _client


class Refused(Exception):
    pass


def effort_kwargs(model, effort):
    """How to ask for reasoning depth. Most models: `reasoning_effort` (the proxy maps it). Claude 5.x models
    only accept adaptive thinking + output_config.effort, and older proxies map reasoning_effort to a thinking
    budget they reject, so for those we send the native fields directly."""
    if any(h and h in model for h in config.ADAPTIVE_HINTS):
        return {"extra_body": {"thinking": {"type": "adaptive"}, "output_config": {"effort": effort}}}
    return {"reasoning_effort": effort}


@tracing.observe(as_type="generation", name="llm")
def structured(*, model, system, user, schema, effort="medium", max_tokens=16000, label=""):
    """Return (parsed pydantic object, usage dict)."""
    tracing.update_generation(name=label or "llm", model=model, input={"system": system[:4000], "user": user},
                              model_parameters={"reasoning_effort": effort})
    t0 = time.time()
    try:
        resp = client().chat.completions.parse(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format=schema,
            **effort_kwargs(model, effort),
        )
    except openai.RateLimitError:
        time.sleep(20)
        return structured(model=model, system=system, user=user, schema=schema, effort=effort,
                          max_tokens=max_tokens, label=label)
    except openai.BadRequestError as e:
        if "tool_choice" not in str(e) and "response_format" not in str(e):
            raise
        # Some proxy/model pairs implement response_format as forced tool use, which newer models reject.
        # Fall back to asking for the JSON in the prompt and validating it ourselves.
        return _json_in_prompt(model, system, user, schema, effort, max_tokens, label, t0)
    choice = resp.choices[0]
    if choice.finish_reason == "content_filter" or getattr(choice.message, "refusal", None):
        raise Refused(f"{model} refused: {getattr(choice.message, 'refusal', '')}")
    if choice.finish_reason == "length":
        raise RuntimeError(f"{label}: hit max_tokens")
    parsed = choice.message.parsed
    if parsed is None and choice.message.content:
        parsed = schema.model_validate_json(choice.message.content)
    usage = {"input": resp.usage.prompt_tokens, "output": resp.usage.completion_tokens} if resp.usage else {}
    tracing.update_generation(output=parsed.model_dump() if parsed else choice.message.content,
                              usage_details=usage, model=resp.model,
                              metadata={"seconds": round(time.time() - t0, 2)})
    if parsed is None:
        raise RuntimeError(f"{label}: no parsed output")
    return parsed, usage


def _json_in_prompt(model, system, user, schema, effort, max_tokens, label, t0, attempts=2):
    import json as _json
    sys2 = (system + "\n\nReply with ONLY one JSON object (no prose, no code fences) that matches this JSON schema:\n"
            + _json.dumps(schema.model_json_schema()))
    last = None
    for _ in range(attempts):
        resp = client().chat.completions.create(
            model=model, max_tokens=max_tokens,
            messages=[{"role": "system", "content": sys2}, {"role": "user", "content": user}],
            **effort_kwargs(model, effort))
        text = (resp.choices[0].message.content or "").strip()
        if text.startswith("```"):
            text = text.strip("`").split("\n", 1)[1] if "\n" in text else text
            text = text.rsplit("```", 1)[0]
        try:
            parsed = schema.model_validate_json(text[text.find("{"):text.rfind("}") + 1])
        except Exception as e:  # noqa: BLE001
            last = e
            continue
        usage = {"input": resp.usage.prompt_tokens, "output": resp.usage.completion_tokens} if resp.usage else {}
        tracing.update_generation(output=parsed.model_dump(), usage_details=usage, model=resp.model,
                                  metadata={"seconds": round(time.time() - t0, 2), "mode": "json-in-prompt"})
        return parsed, usage
    raise RuntimeError(f"{label}: could not parse JSON from {model}: {last}")


def has_key():
    return bool(config.LLM_API_KEY) or config.MOCK


def proxy_up():
    """True when the proxy answers and knows the three aliases."""
    try:
        names = {m.id for m in client().models.list().data}
    except Exception:
        return False, set()
    return {config.WRITER_MODEL, config.JUDGE_MODEL, config.AGENT_MODEL} <= names, names
