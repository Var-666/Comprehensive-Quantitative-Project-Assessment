"""OpenAI-compatible candidate adapter, bounded I/O and deterministic status handling."""

import ipaddress
import json
import socket
import time
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import httpx

from .config import settings
from .services import fail

client_factory = httpx.Client
resolve_host = socket.getaddrinfo
# Reasoning models consume the output budget before returning a short final answer.
TEST_MAX_TOKENS = 128


def validate_base_url(value, resolve=False, allow_unlisted=False):
    value = value.strip()
    try:
        parsed = urlsplit(value)
        hostname = (parsed.hostname or "").encode("idna").decode("ascii").lower()
        port = parsed.port or 443
    except (ValueError, UnicodeError, RecursionError):
        fail(422, "LLM_URL_INVALID", "服务地址格式无效")
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or port < 1
        or port > 65535
        or any(c.isspace() or ord(c) < 32 for c in value)
        or "\\" in value
        or "%" in parsed.netloc
    ):
        fail(422, "LLM_URL_INVALID", "仅允许无凭据、查询参数或片段的HTTPS服务地址")
    if parsed.path and (
        not parsed.path.startswith("/")
        or ".." in parsed.path
        or "%" in parsed.path
        or "//" in parsed.path
    ):
        fail(422, "LLM_URL_INVALID", "服务路径不允许编码、回退或重复分隔符")
    hostport = hostname if port == 443 else f"{hostname}:{port}"
    origin = "https://" + hostport
    allowed = {v.strip().rstrip("/") for v in settings.llm_allowed_origins.split(",") if v.strip()}
    private = {v.strip().rstrip("/") for v in settings.llm_private_origins.split(",") if v.strip()}
    if origin not in allowed and not allow_unlisted:
        fail(
            422, "LLM_URL_NOT_ALLOWED", "服务地址未列入部署白名单，请由运维确认准确HTTPS域名和端口"
        )
    if hostname == "localhost" or hostname.endswith((".localhost", ".local")):
        fail(422, "LLM_URL_UNSAFE", "禁止访问本机及本地管理地址")
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None

    def check_ip(address):
        ip = ipaddress.ip_address(address.split("%")[0])
        if (
            ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_unspecified
            or ip.is_reserved
        ):
            fail(422, "LLM_URL_UNSAFE", "禁止访问回环、云元数据或保留地址")
        if not ip.is_global and origin not in private:
            fail(422, "LLM_PRIVATE_NETWORK_NOT_ALLOWED", "专用网络地址需要部署显式白名单授权")

    if literal:
        check_ip(str(literal))
    if resolve:
        try:
            addresses = resolve_host(hostname, port, type=socket.SOCK_STREAM)
        except OSError:
            fail(502, "LLM_NETWORK_ERROR", "网络连接或服务地址异常：域名无法解析")
        if not addresses:
            fail(502, "LLM_NETWORK_ERROR", "域名没有可用地址")
        for addr in addresses:
            check_ip(addr[4][0])
    return urlunsplit(("https", hostport, parsed.path.rstrip("/"), "", ""))


@dataclass
class ProviderError(Exception):
    code: str
    message: str
    http_status: int | None = None
    service_status: str = "unknown"
    auth_status: str = "unknown"
    list_status: str = "unknown"


def status_error(status):
    if status == 401:
        return ProviderError(
            "LLM_AUTH_FAILED", "API Key 无效或认证失败", status, "reachable", "failed", "unknown"
        )
    if status == 403:
        return ProviderError(
            "LLM_PERMISSION_DENIED",
            "当前账号无权限执行此操作",
            status,
            "reachable",
            "forbidden",
            "unknown",
        )
    if status == 404:
        return ProviderError(
            "LLM_ENDPOINT_UNSUPPORTED",
            "当前服务可能不支持该接口；不能据此认定 API Key 无效或模型不可用",
            status,
            "reachable",
            "unknown",
            "unsupported",
        )
    if status == 429:
        return ProviderError("LLM_RATE_LIMITED", "请求达到限制，请稍后重试", status, "reachable")
    if 300 <= status < 400:
        return ProviderError(
            "LLM_REDIRECT_BLOCKED", "服务返回重定向，出于安全原因未跟随", status, "reachable"
        )
    if status >= 500:
        return ProviderError("LLM_UPSTREAM_ERROR", "MaaS 服务异常，请稍后重试", status, "reachable")
    return ProviderError(
        "LLM_REQUEST_REJECTED", "平台拒绝请求，请核对接口兼容性与部署配置", status, "reachable"
    )


class OpenAICompatibleAdapter:
    def __init__(self, base_url, key, timeout=20, factory=None):
        self.base_url = base_url
        self.key = key
        self.timeout = timeout
        self.factory = factory or client_factory

    def request(self, method, path, body=None):
        try:
            base = validate_base_url(self.base_url, resolve=True)
        except Exception as exc:
            from fastapi import HTTPException

            if isinstance(exc, HTTPException):
                raise ProviderError(exc.detail["code"], exc.detail["message"]) from None
            raise
        started = time.monotonic()
        try:
            with self.factory(
                timeout=httpx.Timeout(self.timeout, connect=min(self.timeout, 10)),
                follow_redirects=False,
                trust_env=False,
                verify=True,
            ) as client:
                with client.stream(
                    method,
                    base + path,
                    headers={
                        "Authorization": "Bearer " + self.key.get_secret_value(),
                        "Accept": "application/json",
                    },
                    json=body,
                ) as response:
                    if response.status_code != 200:
                        raise status_error(response.status_code)
                    chunks = []
                    size = 0
                    for chunk in response.iter_bytes():
                        if time.monotonic() - started > self.timeout:
                            raise ProviderError(
                                "LLM_TIMEOUT", "网络连接或服务地址异常：请求超过总时限"
                            )
                        size += len(chunk)
                        if size > 1024 * 1024:
                            raise ProviderError(
                                "LLM_RESPONSE_TOO_LARGE",
                                "平台响应超过1MB限制",
                                200,
                                "reachable",
                                "unknown",
                            )
                        chunks.append(chunk)
                    try:
                        data = json.loads(b"".join(chunks))
                    except (ValueError, UnicodeError, RecursionError):
                        raise ProviderError(
                            "LLM_RESPONSE_INVALID",
                            "接口返回非JSON内容，请确认平台响应格式",
                            200,
                            "reachable",
                            "unknown",
                        ) from None
                    return data
        except httpx.TimeoutException:
            raise ProviderError("LLM_TIMEOUT", "网络连接或服务地址异常：请求超时") from None
        except httpx.HTTPError:
            raise ProviderError(
                "LLM_NETWORK_ERROR", "网络连接或服务地址异常，请检查网络、地址与TLS证书"
            ) from None

    def models(self):
        raw = self.request("GET", "/models")
        if not isinstance(raw, dict) or not isinstance(raw.get("data"), list):
            raise ProviderError(
                "LLM_MODELS_FORMAT_UNSUPPORTED",
                "模型列表字段缺失或响应格式非标准，请确认平台适配器；认证状态尚不能确认",
                200,
                "reachable",
                "unknown",
                "invalid",
            )
        values = []
        invalid = 0
        seen = set()
        secret = self.key.get_secret_value()
        if len(raw["data"]) > 2000:
            raise ProviderError(
                "LLM_RESPONSE_TOO_LARGE",
                "模型列表超过2000项，请使用平台筛选或专用适配器",
                200,
                "reachable",
                "unknown",
                "invalid",
            )
        for item in raw["data"]:
            model_id = item.get("id") if isinstance(item, dict) else None
            name = (
                (item.get("name") or item.get("display_name") or model_id)
                if isinstance(item, dict)
                else None
            )
            if (
                not isinstance(model_id, str)
                or not model_id
                or len(model_id) > 256
                or model_id != model_id.strip()
                or any(ord(c) < 32 or ord(c) == 127 for c in model_id)
                or secret in model_id
            ):
                invalid += 1
                continue
            if (
                not isinstance(name, str)
                or not name.strip()
                or len(name) > 256
                or secret in name
                or any(ord(c) < 32 for c in name)
            ):
                name = model_id
            if model_id not in seen:
                values.append({"model_id": model_id, "display_name": name})
                seen.add(model_id)
        if raw["data"] and not values:
            raise ProviderError(
                "LLM_MODELS_FORMAT_UNSUPPORTED",
                "响应未包含可保存的模型ID，请确认实际格式",
                200,
                "reachable",
                "unknown",
                "invalid",
            )
        return values, invalid

    def chat(self, model_id, messages, response_format=None, test=False):
        body = {"model": model_id, "messages": messages}
        if test:
            body["max_tokens"] = TEST_MAX_TOKENS
            body["stream"] = False
        if response_format:
            body["response_format"] = response_format
        raw = self.request("POST", "/chat/completions", body)
        try:
            choice = raw["choices"][0]
            content = choice["message"]["content"]
            if test and choice.get("finish_reason") == "length":
                raise ProviderError(
                    "LLM_TEST_OUTPUT_TRUNCATED",
                    "模型输出达到测试长度上限，尚未完成最终正文；本次不标记为可用，并非接口格式不兼容",
                    200,
                    "reachable",
                    "accepted_for_chat_endpoint",
                )
            if (
                not isinstance(content, str)
                or not content.strip()
                or choice.get("finish_reason") not in ("stop", "length")
            ):
                raise ValueError()
            if self.key.get_secret_value() in content:
                raise ValueError()
        except (KeyError, IndexError, TypeError, ValueError):
            raise ProviderError(
                "LLM_CHAT_FORMAT_UNSUPPORTED",
                "模型调用响应格式未通过校验；请核对平台Chat Completions兼容性",
                200,
                "reachable",
                "unknown",
            ) from None
        return choice
