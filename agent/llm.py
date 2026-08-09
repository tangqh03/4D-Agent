"""OpenAI-compatible LLM client for the AMAP gateway (key rotation + retry).

Keys live in agent/llm_keys.local.json (chmod 600) — never copy into docs.
"""
import itertools
import json
import os
import time
import urllib.request
import urllib.error

_cfg_path = os.path.join(os.path.dirname(__file__), "llm_keys.local.json")
if os.path.exists(_cfg_path):
    _CFG = json.load(open(_cfg_path))
else:
    _CFG = {
        "base_url": os.environ.get("VISTR_LLM_BASE_URL", ""),
        "model": os.environ.get("VISTR_LLM_MODEL", ""),
        "api_keys": [k for k in os.environ.get("VISTR_LLM_API_KEYS", "").split(",") if k],
    }
BASE_URL = _CFG["base_url"]
MODEL = os.environ.get("VISTR_LLM_MODEL") or _CFG["model"]
_keys = itertools.cycle(_CFG["api_keys"]) if _CFG["api_keys"] else itertools.cycle([""])


def chat(messages, max_tokens=1500, temperature=0.0, timeout=180, retries=4,
         model=None):
    """One chat completion. Rotates API keys; backs off on 429/5xx.

    Returns both the final answer and the provider's reasoning field when the
    OpenAI-compatible server exposes one (vLLM/Qwen uses ``reasoning``).
    """
    body = json.dumps({"model": model or MODEL, "messages": messages,
                       "max_tokens": max_tokens,
                       "temperature": temperature}).encode()
    last_err = None
    for attempt in range(retries):
        key = next(_keys)
        req = urllib.request.Request(
            BASE_URL + "/chat/completions", data=body,
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read())
            if "choices" not in d or not d["choices"]:
                last_err = f"No choices in response: {json.dumps(d)[:300]}"
                time.sleep(min(2 ** attempt * 3, 45))
                continue
            choice = d["choices"][0]
            message = choice.get("message", {})
            return {
                "content": message.get("content") or "",
                "reasoning": (message.get("reasoning")
                              or message.get("reasoning_content") or ""),
                "usage": d.get("usage", {}),
            }
        except urllib.error.HTTPError as e:
            code = e.code
            detail = e.read()[:300]
            last_err = f"HTTP {code}: {detail}"
            if code in (429, 500, 502, 503, 504):
                time.sleep(min(2 ** attempt * 3, 45))
                continue
            raise RuntimeError(last_err)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError,
                ConnectionResetError, OSError) as e:
            last_err = str(e)
            time.sleep(min(2 ** attempt * 3, 45))
    raise RuntimeError(f"chat failed after {retries} tries: {last_err}")
