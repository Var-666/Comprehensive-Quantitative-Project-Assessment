"""Prove credential lifecycle, discovery/inference separation and live scenario routing."""

import json
import socket

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import ai_service, llm_provider
from app.config import settings
from app.llm_models import SERVICE_ID, LLMConfig, LLMModel, LLMSelection
from app.llm_service import LLMService
from app.models import AuditEvent
from conftest import login_as

BASE = "/api/v1/settings/llm"
KEY = "unit-only-secret-alpha-credential"
KEY2 = "unit-only-secret-beta-credential"


@pytest.fixture(autouse=True)
def secure_environment(client, monkeypatch):
    client.base_url = httpx.URL("https://testserver")
    monkeypatch.setattr(
        settings,
        "llm_encryption_key",
        __import__("pydantic").SecretStr(Fernet.generate_key().decode()),
    )
    monkeypatch.setattr(settings, "llm_encryption_key_file", "")
    monkeypatch.setattr(settings, "llm_allow_local_http_credentials", False)
    monkeypatch.setattr(settings, "ai_provider", "mock")
    monkeypatch.setattr(settings, "ai_base_url", "")
    monkeypatch.setattr(settings, "ai_model", "")
    monkeypatch.setattr(settings, "ai_api_key", __import__("pydantic").SecretStr(""))
    monkeypatch.setattr(
        settings, "llm_allowed_origins", "https://maas-api.cmhk.com,https://other.example:8443"
    )
    monkeypatch.setattr(settings, "llm_private_origins", "")
    monkeypatch.setattr(
        llm_provider,
        "resolve_host",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )


def value(response, status=200):
    assert response.status_code == status, response.text
    return response.json()["data"]


def config(client):
    return value(client.get(BASE))


def save(client, **changes):
    current = config(client)
    data = {
        k: current[k]
        for k in ("service_name", "base_url", "adapter", "mode", "enabled", "timeout_seconds")
    }
    return client.put(
        BASE, headers={"If-Match": str(current["row_version"])}, json={**data, **changes}
    )


def key(client, secret=KEY):
    current = config(client)
    return client.put(
        BASE + "/credential",
        headers={"If-Match": str(current["row_version"])},
        json={"api_key": secret},
    )


def fake(monkeypatch, handler):
    def factory(**kw):
        return httpx.Client(transport=httpx.MockTransport(handler), **kw)

    monkeypatch.setattr(llm_provider, "client_factory", factory)
    monkeypatch.setattr(ai_service, "client_factory", factory)


def fake_ok(monkeypatch, calls=None):
    def handler(request):
        if calls is not None:
            calls.append(request)
        if request.url.path.endswith("/models"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "model-a", "name": "平台返回的模型A"},
                        {"id": "model-b", "display_name": "平台返回的模型B"},
                    ]
                },
            )
        body = json.loads(request.content)
        if "response_format" in body:
            facts = json.loads(body["messages"][1]["content"])
            content = json.dumps(
                {
                    "overview": [f["id"] for f in facts if f["section"] == "overview"],
                    "attention": [f["id"] for f in facts if f["section"] == "attention"],
                    "suggestion_codes": ["prepare_actions"],
                }
            )
        else:
            assert body["max_tokens"] == 128
            content = "OK"
        return httpx.Response(
            200, json={"choices": [{"finish_reason": "stop", "message": {"content": content}}]}
        )

    fake(monkeypatch, handler)


def refresh(client):
    return value(
        client.post(
            BASE + "/models/refresh", headers={"If-Match": str(config(client)["row_version"])}
        )
    )


def manual(client, code="manual-exact-model-id"):
    return value(
        client.post(
            BASE + "/models",
            headers={"If-Match": str(config(client)["row_version"])},
            json={"model_id": code},
        ),
        201,
    )


def test_model(client, model):
    return value(
        client.post(
            BASE + f"/models/{model['id']}/test", headers={"If-Match": str(model["row_version"])}
        )
    )


# Helper is not a standalone pytest case.
test_model.__test__ = False


def choose(client, model):
    return client.put(
        BASE + "/default-model",
        headers={"If-Match": str(config(client)["row_version"])},
        json={"model_config_id": model["id"] if model else None},
    )


def test_persisted_address_and_optimistic_conflict(client, factory):
    initial = config(client)
    assert initial["base_url"] == "https://maas-api.cmhk.com/v1"
    assert initial["key_configured"] is False
    value(save(client, service_name="企业测试网关", base_url="https://other.example:8443/v2"))
    with factory() as db:
        assert db.get(LLMConfig, SERVICE_ID).base_url == "https://other.example:8443/v2"
    assert (
        client.put(
            BASE,
            headers={"If-Match": "0"},
            json={"service_name": "覆盖", "base_url": "https://maas-api.cmhk.com/v1"},
        ).status_code
        == 409
    )


def test_credential_lifecycle_encrypts_and_never_falls_back(client, factory, monkeypatch, caplog):
    value(key(client))
    with factory() as db:
        obj = db.get(LLMConfig, SERVICE_ID)
        ciphertext = obj.encrypted_api_key
        assert KEY not in ciphertext
        assert (
            Fernet(settings.llm_encryption_key.get_secret_value())
            .decrypt(ciphertext.encode())
            .decode()
            == KEY
        )
    calls = []
    fake_ok(monkeypatch, calls)
    assert refresh(client)["result"]["ok"]
    assert calls[-1].headers["authorization"] == "Bearer " + KEY
    value(key(client, KEY2))
    assert refresh(client)["result"]["ok"]
    assert calls[-1].headers["authorization"] == "Bearer " + KEY2
    for path in ["", "/models", "/audit-events", "/call-logs"]:
        response = client.get(BASE + path)
        assert (
            KEY not in response.text
            and KEY2 not in response.text
            and ciphertext not in response.text
        )
    monkeypatch.setattr(settings, "ai_api_key", __import__("pydantic").SecretStr(KEY))
    value(
        client.delete(
            BASE + "/credential", headers={"If-Match": str(config(client)["row_version"])}
        )
    )
    count = len(calls)
    result = refresh(client)["result"]
    assert result["code"] == "LLM_CREDENTIAL_MISSING" and len(calls) == count
    assert not config(client)["key_configured"]
    assert KEY not in caplog.text and KEY2 not in caplog.text
    with factory() as db:
        assert db.get(LLMConfig, SERVICE_ID).encrypted_api_key is None
        assert all(
            KEY not in json.dumps(e.after_json) and KEY2 not in json.dumps(e.after_json)
            for e in db.scalars(select(AuditEvent))
        )


def test_missing_credential_is_not_a_successful_test(client, monkeypatch):
    fake(monkeypatch, lambda req: pytest.fail("未配置Key不得请求平台"))
    response = value(client.post(BASE + "/test-connection", headers={"If-Match": "0"}))
    assert not response["result"]["ok"]
    assert response["result"]["code"] == "LLM_CREDENTIAL_MISSING"
    assert response["result"]["service_status"] == "unknown"


@pytest.mark.parametrize(
    ("status", "code", "auth", "listing"),
    [
        (401, "LLM_AUTH_FAILED", "failed", "unknown"),
        (403, "LLM_PERMISSION_DENIED", "forbidden", "unknown"),
        (404, "LLM_ENDPOINT_UNSUPPORTED", "unknown", "unsupported"),
        (429, "LLM_RATE_LIMITED", "unknown", "unknown"),
        (500, "LLM_UPSTREAM_ERROR", "unknown", "unknown"),
    ],
)
def test_provider_statuses_are_distinct_and_sanitized(
    client, monkeypatch, status, code, auth, listing
):
    value(key(client))
    fake(
        monkeypatch,
        lambda req: httpx.Response(status, json={"message": KEY + " internal private diagnostics"}),
    )
    result = refresh(client)["result"]
    assert result["code"] == code and result["http_status"] == status
    assert result["authentication_status"] == auth and result["model_list_status"] == listing
    assert KEY not in json.dumps(result)
    assert result["ok"] is False


@pytest.mark.parametrize(
    "kind",
    [
        "timeout",
        "network",
        "invalid_json",
        "missing_data",
        "empty",
        "partial",
        "redirect",
        "deeply_nested",
    ],
)
def test_connection_edge_cases_do_not_fabricate_models(client, monkeypatch, kind):
    value(key(client))
    calls = []

    def handler(req):
        calls.append(req)
        if kind == "timeout":
            raise httpx.ReadTimeout(KEY, request=req)
        if kind == "network":
            raise httpx.ConnectError(KEY, request=req)
        if kind == "invalid_json":
            return httpx.Response(200, text="<html>login required</html>")
        if kind == "deeply_nested":
            return httpx.Response(200, text=("[" * 1500) + ("]" * 1500))
        if kind == "missing_data":
            return httpx.Response(200, json={"models": ["invented-interface"]})
        if kind == "empty":
            return httpx.Response(200, json={"data": []})
        if kind == "partial":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "actual-platform-id", "name": "平台实际名称"},
                        {"missing": "id"},
                        {"id": KEY},
                    ]
                },
            )
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data"})

    fake(monkeypatch, handler)
    response = refresh(client)
    result = response["result"]
    assert len(calls) == 1, "不自动重试或跟随危险重定向"
    assert KEY not in json.dumps(response)
    if kind == "empty":
        assert result["ok"] and result["model_list_status"] == "empty" and response["models"] == []
    elif kind == "partial":
        assert result["ok"] and result["invalid_entry_count"] == 2
        assert response["models"][0]["model_id"] == "actual-platform-id"
        assert response["models"][0]["verification_status"] == "untested"
    else:
        assert not result["ok"] and response["models"] == []


def test_discovery_and_inference_are_independent_and_manual_fallback_works(client, monkeypatch):
    value(key(client))
    fake_ok(monkeypatch)
    response = refresh(client)
    model = response["models"][0]
    assert model["source"] == "discovered" and model["verification_status"] == "untested"
    assert choose(client, model).status_code == 409
    assert test_model(client, model)["result"]["model_call_status"] == "available"
    value(choose(client, model))
    # A successful list query is not needed for a correctly specified manual ID.
    model = manual(client)
    assert model["source"] == "manual" and model["verification_status"] == "untested"
    tested = test_model(client, model)["model"]
    value(choose(client, tested))
    assert (
        client.delete(
            BASE + f"/models/{tested['id']}", headers={"If-Match": str(tested["row_version"])}
        ).status_code
        == 409
    )
    assert (
        client.put(
            BASE + f"/models/{tested['id']}",
            headers={"If-Match": str(tested["row_version"])},
            json={"enabled": False},
        ).status_code
        == 409
    )
    value(choose(client, None))
    disabled = value(
        client.put(
            BASE + f"/models/{tested['id']}",
            headers={"If-Match": str(tested["row_version"])},
            json={"enabled": False},
        )
    )
    assert not disabled["enabled"] and choose(client, disabled).status_code == 409
    value(
        client.delete(
            BASE + f"/models/{disabled['id']}", headers={"If-Match": str(disabled["row_version"])}
        )
    )


def test_fresh_business_calls_follow_default_and_scenario_models(client, factory, monkeypatch):
    calls = []
    value(key(client))
    fake_ok(monkeypatch, calls)
    models = refresh(client)["models"]
    for model in models:
        assert test_model(client, model)["result"]["ok"]
    value(choose(client, models[0]))
    value(
        client.put(
            BASE + "/scenario-models",
            headers={"If-Match": str(config(client)["row_version"])},
            json={"notification": models[1]["id"]},
        )
    )
    value(save(client, mode="maas", enabled=True))
    facts = [{"id": "KNOWN", "section": "overview", "kind": "count", "text": "项目私密事实不外送"}]
    with factory() as db:
        _, meta = ai_service.arrange(facts, True, db=db, scenario="analysis")
        assert meta["model_id"] == "model-a"
    with factory() as db:
        _, meta = ai_service.arrange(facts, True, db=db, scenario="notification")
        assert meta["model_id"] == "model-b"
    value(choose(client, models[1]))
    with factory() as db:
        _, meta = ai_service.arrange(facts, True, db=db)
        assert meta["model_id"] == "model-b", "无需重启服务即读取最新默认模型"
    assert "项目私密" not in calls[-1].content.decode()
    value(key(client, KEY2))
    with factory() as db:
        with pytest.raises(__import__("fastapi").HTTPException) as exc:
            LLMService.runtime(db)
        assert exc.value.detail["code"] == "LLM_MODEL_NOT_VALIDATED"
    fresh = value(client.get(BASE + "/models"))
    assert all(m["verification_status"] == "untested" for m in fresh)
    assert test_model(client, fresh[1])["result"]["ok"]
    with factory() as db:
        ai_service.arrange(facts, True, db=db)
    assert calls[-1].headers["authorization"] == "Bearer " + KEY2


def test_database_rejects_disabled_selection_even_without_api_validation(
    client, factory, monkeypatch
):
    value(key(client))
    fake_ok(monkeypatch)
    model = manual(client)
    test_model(client, model)
    value(choose(client, model))
    with pytest.raises(IntegrityError):
        with factory.begin() as db:
            db.get(LLMModel, model["id"]).enabled = False
    with pytest.raises(IntegrityError):
        with factory.begin() as db:
            db.add(
                LLMSelection(
                    service_id=SERVICE_ID,
                    scenario="analysis",
                    model_config_id="00000000-0000-0000-0000-000000009999",
                )
            )


def test_only_system_admin_and_https_can_manage_secrets(client):
    client.base_url = httpx.URL("http://testserver")
    assert key(client).status_code == 400
    assert config(client)["key_configured"] is False
    client.base_url = httpx.URL("https://testserver")
    login_as(client, "reviewer")
    for method, path, payload in [
        ("GET", "", None),
        ("GET", "/models", None),
        ("PUT", "/credential", {"api_key": KEY}),
        ("POST", "/models", {"model_id": "m"}),
        ("DELETE", "/credential", None),
    ]:
        response = client.request(method, BASE + path, headers={"If-Match": "0"}, json=payload)
        assert response.status_code == 403


@pytest.mark.parametrize(
    "environment,enabled,host,peer,allowed",
    [
        ("development", True, "127.0.0.1", "127.0.0.1", True),
        ("test", True, "localhost", "::1", True),
        ("production", True, "127.0.0.1", "127.0.0.1", False),
        ("development", False, "127.0.0.1", "127.0.0.1", False),
        ("development", True, "127.0.0.1", "192.168.1.10", False),
        ("development", True, "gateway.example", "127.0.0.1", False),
    ],
)
def test_http_exception_is_explicit_and_restricted_to_local_development(
    monkeypatch, environment, enabled, host, peer, allowed
):
    """Local convenience must not open production, LAN or hostile Host access to credentials."""
    from starlette.requests import Request

    from app.llm_routes import credential_transport_allowed

    monkeypatch.setattr(settings, "app_env", environment)
    monkeypatch.setattr(settings, "llm_allow_local_http_credentials", enabled)
    request = Request(
        {
            "type": "http",
            "scheme": "http",
            "path": "/",
            "server": (host, 8001),
            "client": (peer, 50000),
            "headers": [(b"host", host.encode()), (b"x-forwarded-for", b"127.0.0.1")],
        }
    )
    assert credential_transport_allowed(request) is allowed


def test_local_http_credentials_keep_encryption_redaction_and_admin_controls(
    client, factory, monkeypatch
):
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "llm_allow_local_http_credentials", True)
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as local:
        login_as(local)
        assert config(local)["local_http_credentials_enabled"]
        assert value(key(local))["key_configured"]
        assert value(key(local, KEY2))["key_configured"]
        with factory() as db:
            encrypted = db.get(LLMConfig, SERVICE_ID).encrypted_api_key
            assert KEY2 not in encrypted
            from app.llm_secrets import CredentialVault

            assert CredentialVault.decrypt(encrypted).get_secret_value() == KEY2
        for path in [BASE, BASE + "/audit-events", BASE + "/call-logs"]:
            response = local.get(path)
            assert KEY not in response.text and KEY2 not in response.text
        login_as(local, "reviewer")
        assert (
            local.put(
                BASE + "/credential", headers={"If-Match": "0"}, json={"api_key": KEY}
            ).status_code
            == 403
        )
        login_as(local)
        assert not value(
            local.delete(
                BASE + "/credential", headers={"If-Match": str(config(local)["row_version"])}
            )
        )["key_configured"]
        monkeypatch.setattr(settings, "app_env", "production")
        assert not config(local)["local_http_credentials_enabled"]
        assert key(local).status_code == 400


@pytest.mark.parametrize(
    "url",
    [
        "http://maas-api.cmhk.com/v1",
        "https://user:password@maas-api.cmhk.com/v1",
        "https://maas-api.cmhk.com/v1?key=secret",
        "https://maas-api.cmhk.com:bad/v1",
        "https://evil.example/v1",
        "https://localhost/v1",
        "https://127.0.0.1/v1",
        "https://169.254.169.254/v1",
        "https://[::1]/v1",
        "https://maas-api.cmhk.com/v1/../admin",
        "https://maas-api.cmhk.com/%2fadmin",
    ],
)
def test_unsafe_urls_are_rejected_before_any_request(client, monkeypatch, url):
    fake(monkeypatch, lambda req: pytest.fail("不安全目标不得收到请求"))
    assert save(client, base_url=url).status_code == 422


@pytest.mark.parametrize("address", ["10.1.2.3", "198.18.0.8"])
def test_dns_private_ranges_need_explicit_deployment_policy(client, monkeypatch, address):
    value(key(client))
    monkeypatch.setattr(
        llm_provider,
        "resolve_host",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))],
    )
    fake(monkeypatch, lambda req: pytest.fail("普通白名单不能自动授权内网目标"))
    assert refresh(client)["result"]["code"] == "LLM_PRIVATE_NETWORK_NOT_ALLOWED"
    monkeypatch.setattr(settings, "llm_private_origins", "https://maas-api.cmhk.com")
    fake_ok(monkeypatch)
    assert refresh(client)["result"]["ok"]
    monkeypatch.setattr(
        llm_provider,
        "resolve_host",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 443))],
    )
    assert refresh(client)["result"]["code"] == "LLM_URL_UNSAFE"


def test_environment_migration_is_explicit_and_admin_config_wins(client, monkeypatch):
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "ai_provider", "openai_compatible")
    monkeypatch.setattr(settings, "ai_base_url", "https://maas-api.cmhk.com/v1")
    monkeypatch.setattr(settings, "ai_model", "legacy-model-actual-id")
    monkeypatch.setattr(settings, "ai_api_key", SecretStr(KEY))
    assert config(client)["source"] == "environment"
    assert save(client).status_code == 409
    imported = value(
        client.post(
            BASE + "/import-environment", headers={"If-Match": "0"}, json={"confirmed": True}
        )
    )
    assert imported["source"] == "database" and imported["key_configured"]
    assert imported["mode"] == "mock" and not imported["enabled"]
    assert value(client.get(BASE + "/models"))[0]["verification_status"] == "untested"
    assert (
        client.post(
            BASE + "/import-environment",
            headers={"If-Match": str(imported["row_version"])},
            json={"confirmed": True},
        ).status_code
        == 409
    )
    value(client.delete(BASE + "/credential", headers={"If-Match": str(imported["row_version"])}))
    assert config(client)["key_configured"] is False


def test_missing_master_key_cannot_store_plaintext_and_address_changes_clear_credential(
    client, monkeypatch
):
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "llm_encryption_key", SecretStr(""))
    assert key(client).status_code == 503
    monkeypatch.setattr(settings, "llm_encryption_key", SecretStr(Fernet.generate_key().decode()))
    value(key(client))
    fake_ok(monkeypatch)
    model = refresh(client)["models"][0]
    test_model(client, model)
    value(choose(client, model))
    value(save(client, mode="maas", enabled=True))
    changed = value(save(client, base_url="https://other.example:8443/v1"))
    assert changed["enabled"] is False
    assert changed["key_configured"] is False and changed["selections"] == {}
    assert value(client.get(BASE + "/models")) == [], "旧服务模型不得误用到新地址"


def test_saved_credential_and_scenario_survive_a_new_backend_process(client, factory, monkeypatch):
    import os
    import subprocess
    import sys

    value(key(client))
    fake_ok(monkeypatch)
    model = refresh(client)["models"][0]
    test_model(client, model)
    value(choose(client, model))
    value(save(client, mode="maas", enabled=True))
    with factory() as db:
        url = db.bind.url.render_as_string(hide_password=False)
    script = """from app.db import SessionLocal
from app.llm_service import LLMService
from app.llm_models import LLMConfig,SERVICE_ID
from app.llm_secrets import CredentialVault
import os
with SessionLocal() as db:
    config=db.get(LLMConfig,SERVICE_ID)
    assert config.base_url=='https://maas-api.cmhk.com/v1'
    assert CredentialVault.decrypt(config.encrypted_api_key).get_secret_value()==os.environ['UNIT_EXPECTED_CREDENTIAL']
    runtime=LLMService.runtime(db,'analysis')
    assert runtime.source=='database' and runtime.model_id=='model-a'
print('new backend process: saved configuration and encrypted credential verified')
"""
    response = subprocess.run(
        [sys.executable, "-c", script],
        cwd=__import__("pathlib").Path(__file__).resolve().parents[1],
        env={
            **os.environ,
            "DATABASE_URL": url,
            "LLM_ENCRYPTION_KEY": settings.llm_encryption_key.get_secret_value(),
            "UNIT_EXPECTED_CREDENTIAL": KEY,
        },
        capture_output=True,
        text=True,
    )
    assert response.returncode == 0, response.stderr
    assert KEY not in response.stdout + response.stderr


def test_model_endpoint_unsupported_does_not_prove_invalid_credential(client, monkeypatch):
    value(key(client))
    model = manual(client)
    fake(monkeypatch, lambda request: httpx.Response(404))
    response = test_model(client, model)
    assert response["model"]["verification_status"] == "untested"
    assert response["result"]["authentication_status"] == "unknown"
    assert response["result"]["model_call_status"] == "unsupported_or_unverified"
    assert choose(client, response["model"]).status_code == 409


@pytest.mark.parametrize(
    "finish,content,code,state",
    [
        ("length", None, "LLM_TEST_OUTPUT_TRUNCATED", "incomplete"),
        ("length", "O", "LLM_TEST_OUTPUT_TRUNCATED", "incomplete"),
        ("stop", None, "LLM_CHAT_FORMAT_UNSUPPORTED", "unsupported_or_unverified"),
    ],
)
def test_reasoning_or_partial_output_is_not_mistaken_for_a_usable_final_answer(
    client, monkeypatch, finish, content, code, state
):
    """Reasoning alone is not a final answer; truncation is not an incompatible protocol."""
    value(key(client))
    model = manual(client)
    calls = []

    def handler(request):
        calls.append(request)
        body = json.loads(request.content)
        assert body["max_tokens"] == 128 and not body["stream"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": finish,
                        "message": {"content": content, "reasoning_content": "private reasoning"},
                    }
                ]
            },
        )

    fake(monkeypatch, handler)
    response = test_model(client, model)
    assert len(calls) == 1, "不自动重试增加模型调用费用"
    assert not response["result"]["ok"]
    assert response["result"]["code"] == code
    assert response["result"]["model_call_status"] == state
    assert response["model"]["verification_status"] == "untested"
    assert "private reasoning" not in json.dumps(response)
    assert choose(client, response["model"]).status_code == 409


def test_public_fields_cannot_accidentally_contain_current_key(client):
    value(key(client))
    assert save(client, service_name="gateway " + KEY).status_code == 422
    assert KEY not in client.get(BASE).text


def test_real_report_pipeline_persists_long_provider_model_id(client, factory, monkeypatch):
    """New configured IDs must fit the existing report audit field on PostgreSQL too."""
    from test_evaluation import sample, snapshot

    sample(factory)
    value(key(client))
    fake_ok(monkeypatch)
    model = manual(client, "provider-model-" + ("x" * 150))
    test_model(client, model)
    value(choose(client, model))
    value(save(client, mode="maas", enabled=True))
    project = value(client.get("/api/v1/projects"))["items"][0]
    evidence = snapshot(client, project["id"])
    report = value(
        client.post(
            f"/api/v1/projects/{project['id']}/reports/draft",
            headers={"Idempotency-Key": "configured-long-model"},
            json={"metric_snapshot_id": evidence["id"], "allow_external": True},
        ),
        201,
    )
    assert report["model_id"] == model["model_id"]
    assert report["validation_json"]["configuration_source"] == "database"


@pytest.mark.parametrize("allowed", [True, False])
def test_legacy_custom_endpoint_is_displayed_and_never_silently_replaced(
    client, monkeypatch, allowed
):
    from pydantic import SecretStr

    base = "https://other.example:8443/v1" if allowed else "https://unlisted.example/v1"
    monkeypatch.setattr(settings, "ai_base_url", base)
    monkeypatch.setattr(settings, "ai_api_key", SecretStr(KEY))
    assert config(client)["base_url"] == base
    response = client.put(
        BASE + "/credential",
        headers={"If-Match": "0"},
        json={"api_key": KEY2, "replace_environment": True},
    )
    if allowed:
        assert value(response)["base_url"] == base
    else:
        assert response.status_code == 422
        assert config(client)["source"] == "environment"
        assert config(client)["legacy_warning"]
