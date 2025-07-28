import os, json, requests

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL   = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-r1-0528:free")
BASE_URL           = os.getenv("OPENROUTER_BASE_URL",
                               "https://openrouter.ai/api/v1/chat/completions")

def call_openrouter(system_prompt: str, user_prompt: str) -> str:
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY missing")

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type":  "application/json",
    }
    body = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 400,
    }
    r = requests.post(BASE_URL, headers=headers, data=json.dumps(body), timeout=60)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()
