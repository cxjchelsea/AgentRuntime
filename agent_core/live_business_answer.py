"""GA-15 opt-in real-model business answer grounded in GA-14 evidence.

This application-level sandbox adapter never executes tools or grants authority.
The model can only paraphrase a verified baseline within strict numeric and
non-execution constraints; failure is explicit, not an ungrounded response.
"""

from __future__ import annotations

import json
import re

from agent_core.business_answer import BusinessAnswer
from agent_core.chat_transport import (
    ChatCompletionsConfig,
    ChatCompletionsStrategyTransport,
)
from agent_core.runner import RunBoundaryError

_DIGITS = re.compile(r"\d+")
_UNSUPPORTED = (
    "已经采购",
    "已采购",
    "采购成功",
    "已补货",
    "补货成功",
    "库存已更新",
    "已经完成学习",
    "已帮你完成",
    "已替你完成",
)


def _expected_metrics(baseline: BusinessAnswer, operation: str) -> tuple[str, ...]:
    if operation == "inventory_replenishment":
        metrics = re.search(r"可用库存为 (\d+) 件.*?(?:建议补货 (\d+) 件|暂不需要补货)", baseline.text)
        if metrics is None:
            raise RunBoundaryError("invalid inventory answer baseline")
        available, reorder = metrics.group(1), metrics.group(2) or "0"
        return (available, reorder)
    if operation == "learning_progress":
        metrics = re.search(r"进度为 (\d+)%，剩余 (\d+) 项", baseline.text)
        if metrics is None:
            raise RunBoundaryError("invalid learning answer baseline")
        return metrics.groups()
    raise RunBoundaryError("unregistered business response domain")


async def generate_live_business_answer(
    *,
    baseline: BusinessAnswer,
    operation: str,
    config: ChatCompletionsConfig,
) -> BusinessAnswer:
    """Ask real model for a bounded JSON answer, validate before accepting."""
    if type(baseline) is not BusinessAnswer or not baseline.source_digests:
        raise RunBoundaryError("unverified business response baseline")
    values = _expected_metrics(baseline, operation)
    if len(baseline.question) > 1000 or len(baseline.text) > 1000:
        raise RunBoundaryError("business response prompt too large")
    instruction = (
        "你是业务信息播报助手，仅允许报告提供的已验证事实。"
        "不可声称实际执行过采购、补货、库存更新或学习任务。"
        "不得添加任何新数字。必须保持数据含义和未执行声明。"
        "仅返回一个 JSON 对象，唯一字段是 answer（字符串），不加 Markdown。"
    )
    user = json.dumps(
        {
            "question": baseline.question,
            "verified_answer": baseline.text,
            "allowed_metrics": list(values),
            "read_only": True,
        },
        ensure_ascii=False,
    )
    transport = ChatCompletionsStrategyTransport(
        config,
        system_instruction=instruction,
        message_builder=lambda _payload: (
            {"role": "system", "content": instruction},
            {"role": "user", "content": user},
        ),
    )
    result = await transport({"legal_strategy_ids": [], "candidate_action_ids": []})
    if set(result) != {"answer"} or type(result["answer"]) is not str:
        raise RunBoundaryError("untrusted model answer contract")
    answer = result["answer"].strip()
    if (
        not 1 <= len(answer) <= 500
        or any(term in answer for term in _UNSUPPORTED)
        or set(_DIGITS.findall(answer)) != set(values)
    ):
        raise RunBoundaryError("ungrounded model business answer")
    if operation == "inventory_replenishment":
        available, quantity = values
        if (
            f"{available}" not in answer
            or ("补货" not in answer and "库存" not in answer)
            or ("未执行" not in answer and "没有执行" not in answer and "尚未" not in answer)
            or (quantity != "0" and f"{quantity}" not in answer)
        ):
            raise RunBoundaryError("model inventory answer not grounded")
    else:
        progress, remaining = values
        if (
            f"{progress}%" not in answer
            or f"{remaining}" not in answer
            or ("没有" not in answer and "未" not in answer)
            or "学习" not in answer
        ):
            raise RunBoundaryError("model learning answer not grounded")
    return BusinessAnswer(
        run_id=baseline.run_id,
        domain_id=baseline.domain_id,
        question=baseline.question,
        text=answer,
        source_digests=baseline.source_digests,
    )
