"""HTTPS browser acceptance harness; explicit HTTP doubles, never a product provider."""

import json
import socket

import httpx

from app import ai_service, llm_provider
from app.config import settings
from app.main import app  # noqa: F401

if settings.app_env != "test":
    raise RuntimeError("Browser HTTP doubles are allowed only in the isolated test harness")


def handler(request):
    if request.url.path.endswith("/models"):
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "http-double-analysis", "name": "HTTP替身：分析测试模型"},
                    {"id": "http-double-blocked", "name": "HTTP替身：无调用权限模型"},
                    {"id": "http-double-notice", "name": "HTTP替身：通知测试模型"},
                ]
            },
        )
    body = json.loads(request.content)
    if body.get("model") == "http-double-blocked":
        return httpx.Response(403, json={"error": "fixture-model-permission-denied"})
    if body.get("response_format"):
        facts = json.loads(body["messages"][1]["content"])
        content = json.dumps(
            {
                "overview": [f["id"] for f in facts if f["section"] == "overview"],
                "attention": [f["id"] for f in facts if f["section"] == "attention"],
                "suggestion_codes": ["prepare_actions"],
            }
        )
    else:
        content = "OK"
    return httpx.Response(
        200, json={"choices": [{"finish_reason": "stop", "message": {"content": content}}]}
    )


def factory(**kwargs):
    return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)


llm_provider.client_factory = factory
ai_service.client_factory = factory
llm_provider.resolve_host = lambda *args, **kwargs: [
    (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
]
