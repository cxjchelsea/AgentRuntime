"""GA-22 application-owned, typed goal policy; no execution authority.

The host injects an admitted policy for a pinned domain. This is NOT yet a
signed domain-package schema or production permission grant. All fresh
observations must come from the existing approved read-only Agent runner.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GoalUpdate:
    domain: str
    goal_key: str
    value: int


@dataclass(frozen=True, slots=True)
class DomainGoalPolicy:
    domain: str
    goal_key: str
    update_pattern: str
    metric_key: str
    metric_label: str
    target_label: str
    delta_label: str
    unit: str
    max_value: int = 100_000

    def __post_init__(self) -> None:
        if (
            not all(
                type(x) is str and 1 <= len(x) <= 128
                for x in (
                    self.domain, self.goal_key, self.metric_key,
                    self.metric_label, self.target_label,
                    self.delta_label, self.unit,
                )
            )
            or type(self.update_pattern) is not str
            or not 1 <= len(self.update_pattern) <= 256
            or type(self.max_value) is not int
            or not 1 <= self.max_value <= 100_000
        ):
            raise ValueError("invalid goal policy")
        try:
            compiled = re.compile(self.update_pattern)
        except re.error as exc:
            raise ValueError("invalid goal pattern") from exc
        if compiled.groups != 1:
            raise ValueError("goal pattern must capture exactly one value")

    def parse(self, text: str) -> GoalUpdate:
        if type(text) is not str or not 1 <= len(text.strip()) <= 1000:
            raise ValueError("invalid goal update text")
        matches = list(re.finditer(self.update_pattern, text))
        if len(matches) != 1 or len(re.findall(r"\d+", text)) != 1:
            raise ValueError("ambiguous or unsupported goal update")
        raw = matches[0].group(1)
        if not raw.isdecimal():
            raise ValueError("goal value must be a nonnegative integer")
        number = int(raw)
        if not 0 <= number <= self.max_value:
            raise ValueError("goal update exceeds domain policy bounds")
        return GoalUpdate(self.domain, self.goal_key, number)

    def render(self, update: GoalUpdate, metrics: object) -> str:
        if update.domain != self.domain or update.goal_key != self.goal_key:
            raise ValueError("foreign domain goal update")
        if (
            type(metrics) is not dict
            or set(metrics) != {self.metric_key}
            or type(metrics[self.metric_key]) is not int
            or not 0 <= metrics[self.metric_key] <= 100_000
        ):
            raise ValueError("fresh verified domain metric required")
        metric = metrics[self.metric_key]
        delta = max(0, update.value - metric)
        return (
            f"重新查询验证{self.metric_label}为 {metric} {self.unit}；"
            f"按新{self.target_label} {update.value} {self.unit}，"
            f"{self.delta_label} {delta} {self.unit}。"
            "只进行了只读查询和重新计算，没有执行任何业务修改。"
        )


def inventory_goal_policy() -> DomainGoalPolicy:
    """Demo host policy, not a hardcoded Core enumeration."""
    return DomainGoalPolicy(
        domain="inventory",
        goal_key="target",
        update_pattern=r"(?:库存)?目标(?:改成|改为|调整为|设为|设成|设置为|是)\s*(\d{1,6})\s*件?",
        metric_key="available",
        metric_label="可用库存",
        target_label="库存目标",
        delta_label="建议补货",
        unit="件",
    )
