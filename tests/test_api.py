"""
test_api.py — manual check that LLM_API_KEY (from .env or the environment)
is valid and can reach the configured Anthropic endpoint. Run from the repo
root: python tests/test_api.py

Reuses agents.qa_common's already-configured client (same base_url handling,
including the /v1 double-path fix) instead of constructing a new one here.
"""
from src.core.qa_common import client, client_ready, VISION_MODEL

if not client_ready():
    raise SystemExit("LLM client not ready -- set LLM_API_KEY in .env or the environment.")

try:
    response = client.messages.create(
        model=VISION_MODEL,
        max_tokens=10,
        messages=[{"role": "user", "content": "Say hello"}],
    )
    print("API working:", response.content[0].text)
except Exception as e:
    print("API error:", e)
