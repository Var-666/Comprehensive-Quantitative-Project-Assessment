"""Models classify/select existing facts only. Rendering and status/retry decisions are deterministic."""

import json
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .llm_service import LLMService
from .services import fail

client_factory = httpx.Client

SUGGESTIONS = {
    "verify_records": "建议优先补充待核对记录的来源并安排独立核实；不能将缺失数据直接认定为延期。",
    "review_schedule": "建议复核计划偏差及后续节点安排；本报告不认定延期责任或因果关系。",
    "prepare_actions": "建议按已批准的标准动作确认工作准备、执行人及核实依据。",
    "verify_finance": "建议由获授权的财务人员核对计划与实际凭证；计划金额不代表实际发生。",
}


class Arrangement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    overview: list[str] = Field(max_length=100)
    attention: list[str] = Field(max_length=100)
    suggestion_codes: list[
        Literal["verify_records", "review_schedule", "prepare_actions", "verify_finance"]
    ] = Field(max_length=4)


def arrange(facts, allow_external=False, *, db=None, scenario="analysis"):
    runtime = LLMService.runtime(db, scenario)
    if any(
        sum(f["section"] == section for f in facts) > 100 for section in ("overview", "attention")
    ):
        fail(422, "FACT_BUNDLE_TOO_LARGE", "事实分组超过100项，请缩小报告范围")
    allowed = {f["id"] for f in facts}
    if runtime.provider == "mock":
        result = Arrangement(
            overview=[f["id"] for f in facts if f["section"] == "overview"],
            attention=[f["id"] for f in facts if f["section"] == "attention"],
            suggestion_codes=["verify_records", "review_schedule", "prepare_actions"]
            + (["verify_finance"] if any(f.get("financial") for f in facts) else []),
        )
        return result, {
            "generator_type": "mock",
            "model_id": None,
            "label": "Mock · 确定性事实整理，无真实模型连接",
            "external_transmission": False,
        }
    if not runtime.external_enabled or not allow_external:
        fail(
            409, "EXTERNAL_AI_NOT_AUTHORIZED", "真实模型调用需部署配置允许且本次显式授权事实包外送"
        )
    # No names, dates, money amounts or document references leave the application.
    # The provider only sees symbolic fact descriptors, sufficient for classification/order.
    descriptors = [{k: f[k] for k in ("id", "section", "kind")} for f in facts]
    schema = Arrangement.model_json_schema()
    for name in ("overview", "attention"):
        schema["properties"][name]["items"] = {"type": "string", "enum": sorted(allowed)}
    body = {
        "model": runtime.model_id,
        "messages": [
            {
                "role": "system",
                "content": "仅对给定事实ID进行分类与排序；返回JSON，严格符合Schema。overview和attention分别包含对应section的所有ID各一次；不得生成事实、数值、文字或额外字段。选择建议代码。",
            },
            {"role": "user", "content": json.dumps(descriptors)},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "fact_arrangement", "strict": True, "schema": schema},
        },
    }
    raw = LLMService.chat(
        runtime, body["messages"], body["response_format"], db, scenario, client_factory
    )
    if raw.get("finish_reason") != "stop":
        fail(502, "MODEL_OUTPUT_INVALID", "模型输出不完整，未生成报告")
    try:
        result = Arrangement.model_validate_json(raw["message"]["content"])
    except (ValueError, KeyError, TypeError, ValidationError):
        fail(502, "MODEL_OUTPUT_INVALID", "模型输出未通过结构校验，未静默降级Mock")
    for section, key in [("overview", "overview"), ("attention", "attention")]:
        expected = {f["id"] for f in facts if f["section"] == section}
        actual = getattr(result, key)
        if len(actual) != len(set(actual)) or set(actual) != expected:
            fail(502, "MODEL_FACT_REFERENCE_INVALID", "模型遗漏、重复或编造事实引用，输出已拒绝")
    if len(result.suggestion_codes) != len(set(result.suggestion_codes)):
        fail(502, "MODEL_OUTPUT_INVALID", "模型建议代码重复")
    if "verify_finance" in result.suggestion_codes and not any(f.get("financial") for f in facts):
        fail(502, "MODEL_OUTPUT_INVALID", "模型不能添加未提供的财务分析")
    return result, {
        "generator_type": "llm_assisted",
        "model_id": runtime.model_id,
        "configuration_source": runtime.source,
        "configuration_revision": runtime.revision,
        "label": "真实模型辅助分类整理 · 正文事实由后端渲染",
        "external_transmission": True,
        "outbound_fields": ["id", "section", "kind"],
    }


def render(facts, arrangement, heading, meta):
    lookup = {f["id"]: f for f in facts}
    return "\n".join(
        [
            heading,
            meta["label"],
            "一、事实概况",
            *[f"[{key}] {lookup[key]['text']}" for key in arrangement.overview],
            "二、需要关注和待核对事项",
            *[f"[{key}] {lookup[key]['text']}" for key in arrangement.attention],
            "三、工作建议（非业务事实）",
            *[SUGGESTIONS[code] for code in arrangement.suggestion_codes],
            "说明：本报告基于冻结事实包；草稿须独立审核。未生成综合考核分、实际到账推断或责任归因。",
        ]
    )
