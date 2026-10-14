"""GA-20 experimental interactive, read-only business Agent sandbox.

This entry point deliberately reuses GA-15's Linux test-package fixture and
M4 sandbox StepPort. It is NOT a production Domain Package or host authority.
No purchase, inventory update, or study-task mutation is implemented.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_core.business_answer import render_business_answer
from agent_core.chat_transport import ChatCompletionsConfig, ChatCompletionsStrategyTransport
from agent_core.domain_application import bootstrap_domain_application
from agent_core.domain_package_loader import HostPackageRootIssuer, HostPublishedGeneration, LocalPackageLoader, TrustedPackageIdentity
from agent_core.live_business_answer import generate_live_business_answer
from agent_core.model_adapter import StructuredStrategyTransportAdapter
from agent_core.readonly_business_tools import ReadOnlyBusinessTools
from agent_core.runner import LoopBudget, RunBoundaryError, RunKind
from agent_core.sandbox_tool_dispatch import SandboxToolDispatcher
from agent_core.sqlite_business_intake import load_sqlite_business_snapshot
from runtime.contracts import InputSource, InputTriggerType, RuntimeInput
from runtime.understanding import (
    ConfiguredTextRule,
    DeepUnderstandingRequestBuilder,
    DefaultModelContextSelector,
    DeterministicRuleDefinition,
    DeterministicRuleParser,
    ModelUnderstandingOutputValidator,
    RuntimeUnderstandingEngine,
    TextMatchMode,
    UnderstandingPathRouter,
    UnderstandingPostprocessor,
    UnderstandingStateAssembler,
)
from examples.readonly_application_step import ReadOnlyApplicationStep

DEFAULT_QUESTIONS = {
    "inventory": "请查询库存并计算需要补货多少件",
    "learning": "请查询学习进度和剩余学习任务",
}
OPERATIONS = {
    "inventory": "inventory_replenishment",
    "learning": "learning_progress",
}


def validated_question(domain: str, question: str) -> str:
    """Reject out-of-scope tasks rather than quietly executing another task."""
    if domain not in OPERATIONS or not isinstance(question, str):
        raise ValueError("unsupported domain")
    question = question.strip()
    if not 1 <= len(question) <= 1000:
        raise ValueError("question must be 1..1000 characters")
    words = ("库存", "补货", "stock", "inventory", "reorder") if domain == "inventory" else (
        "学习", "进度", "任务", "study", "progress", "lesson",
    )
    if not any(word in question.lower() for word in words):
        raise ValueError("question is outside the selected read-only domain")
    return question


def load_operator_source(config_file: Path, domain: str):
    """Resolve a pinned external package and existing SQLite file, sandbox only."""
    if config_file.is_symlink() or not config_file.is_file():
        raise ValueError("operator config must be a regular file")
    raw = json.loads(config_file.read_text(encoding="utf-8"))
    fields = {"domain", "package_root", "generation_id", "domain_version", "runtime_profile", "manifest_digest", "database_file", "step_keys"}
    if type(raw) is not dict or set(raw) != fields or raw["domain"] != {"inventory": "inventory.reconcile", "learning": "learning.plan"}.get(domain):
        raise ValueError("operator source configuration mismatch")
    if any(type(raw[key]) is not str or not raw[key] for key in fields - {"step_keys"}):
        raise ValueError("operator source values invalid")
    keys = raw["step_keys"]
    if type(keys) is not dict or not keys or any(type(k) is not str or type(v) is not str or not v for k, v in keys.items()):
        raise ValueError("operator step keys invalid")
    root, database = Path(raw["package_root"]), Path(raw["database_file"])
    if not root.is_absolute() or not database.is_absolute() or root.is_symlink() or database.is_symlink():
        raise ValueError("operator sources require absolute non-symlink paths")
    identity = TrustedPackageIdentity(raw["generation_id"], raw["domain"], raw["domain_version"], raw["runtime_profile"], raw["manifest_digest"])
    record = HostPublishedGeneration(identity, str(root), True)
    # This is only an operator-controlled local demo verifier, not an independent host attestation.
    issuer = HostPackageRootIssuer((record,), publication_verifier=lambda candidate: candidate == record)
    with issuer.issue(identity.generation_id) as lease:
        snapshot = LocalPackageLoader().load(lease, identity)
    catalog = bootstrap_domain_application(snapshot).execution_catalog(snapshot)
    if set(keys) != {step.step_id for step in catalog.workflow.steps}:
        raise ValueError("operator step bindings do not match package")
    lookup = load_sqlite_business_snapshot(catalog=catalog, database_file=database, step_keys=keys)
    return snapshot, lookup


async def ask_once(domain: str, question: str, config: ChatCompletionsConfig, operator_config: Path | None = None) -> dict[str, object]:
    """Run the existing real-model/M4/SQLite read-only path, not a canned answer."""
    if not sys.platform.startswith("linux"):
        raise RuntimeError("GA-20 fixture-backed sandbox is Linux-only")
    question = validated_question(domain, question)
    steps = 1 if domain == "inventory" else 2
    operation = OPERATIONS[domain]
    if operator_config is None:
        raise ValueError("--operator-config is required for the application CLI")
    snapshot, lookup = load_operator_source(operator_config, domain)
    app = bootstrap_domain_application(snapshot)
    catalog = app.execution_catalog(snapshot)
    if (
        catalog.binding_fingerprint != lookup.catalog.binding_fingerprint
        or len(catalog.workflow.steps) != steps
    ):
        raise ValueError("operator package not compatible with selected demo domain")
    dispatcher = SandboxToolDispatcher(
        catalog,
        ReadOnlyBusinessTools(
            lookup, {step.step_id: operation for step in catalog.workflow.steps},
        ).handlers(),
    )

    async def selected(payload: dict[str, Any]) -> dict[str, object]:
        stage = "verify-" if payload.get("last_agent_action") == "FACT_1" else "collect-"
        bounded = dict(payload)
        bounded["candidate_action_ids"] = [
            value for value in payload["candidate_action_ids"]
            if value.startswith(stage)
        ]
        bounded["legal_strategy_ids"] = [
            value for value in payload["legal_strategy_ids"]
            if value.startswith(stage.removesuffix("-") + "-strategy-")
        ]
        if len(bounded["candidate_action_ids"]) != 1 or len(bounded["legal_strategy_ids"]) != 1:
            raise ValueError("no uniquely admitted business action")
        action = bounded["candidate_action_ids"][0]
        strategy = bounded["legal_strategy_ids"][0]
        instruction = (
            "You are a read-only business Agent. Return JSON with precisely "
            "strategy_id, action_ids, reason_code. Choose only strategy "
            f"{strategy!r} and action [{action!r}]. "
            "Set reason_code to BUSINESS_READ_ONLY_QUERY. "
            "Never claim any purchase, inventory update, or study completion."
        )
        transport = ChatCompletionsStrategyTransport(
            config, system_instruction=instruction,
        )
        for attempt in range(2):
            response = dict(await transport(bounded))
            if response.get("strategy_id") == strategy and response.get("action_ids") == [action]:
                return response
            if attempt == 0:
                bounded["previous_selection_invalid"] = True
        raise ValueError("model did not choose a legal action")

    initial = RuntimeInput(
        request_id="request-001",
        trace_id="trace-001",
        session_id="session-001",
        subject_id="subject-001",
        identity_scope="scope-001",
        source=InputSource.USER,
        trigger_type=InputTriggerType.USER_TEXT,
        timestamp=datetime.now(UTC),
        text=question,
    )
    run_id = "ga20-sandbox-run"

    planner, validator, rechecker = app.m4(
        StructuredStrategyTransportAdapter(selected),
    )
    # Domain patterns are application-owned M3 configuration, not Core enums.
    # No deep M3 model is used: unsupported inputs fail closed in this sandbox.
    patterns = (
        (r"库存|补货|stock|inventory|reorder",)
        if domain == "inventory"
        else (r"学习|进度|任务|study|progress|lesson",)
    )
    m3 = RuntimeUnderstandingEngine(
        rule_parser=DeterministicRuleParser((
            ConfiguredTextRule(DeterministicRuleDefinition(
                rule_id="ga20-" + domain,
                version="1.0.0",
                patterns=patterns,
                match_mode=TextMatchMode.SEARCH,
                confidence=1.0,
                intent_id="ga20." + domain + ".read",
            )),
        )),
        path_router=UnderstandingPathRouter(),
        request_builder=DeepUnderstandingRequestBuilder(DefaultModelContextSelector()),
        output_validator=ModelUnderstandingOutputValidator(),
        postprocessor=UnderstandingPostprocessor(),
        assembler=UnderstandingStateAssembler(),
    )
    turn = ReadOnlyApplicationStep(
        initial, run_id, app, dispatcher, planner, validator, rechecker,
        m3, "ga20." + domain + ".read", "GA20_READ_ONLY_" + domain.upper(),
    )

    outcome = await app.run(
        initial,
        run_id=run_id,
        step=turn,
        budget=LoopBudget(
            max_iterations=steps + 2,
            max_executions=steps + 1,
            max_decision_seconds=55.0,
            max_execution_seconds=5.0,
        ),
        execution_catalog=catalog,
    )
    if outcome.kind is not RunKind.FINISH:
        raise RuntimeError(f"Agent did not finish: {outcome.kind.value}")
    baseline = render_business_answer(
        question=question, outcome=outcome, lookup=lookup, operation=operation,
    )
    # Fail closed on ungrounded model paraphrase. A verified deterministic
    # answer is safer and more available than accepting an invalid LLM claim.
    # No tool call or external side effect is retried by this fallback.
    answer_mode = "verified_model"
    try:
        answer = await generate_live_business_answer(
            baseline=baseline, operation=operation, config=config,
        )
    except RunBoundaryError:
        answer = baseline
        answer_mode = "verified_deterministic_fallback"
    return {
        "domain": domain,
        "question": question,
        "answer": answer.text,
        "answer_mode": answer_mode,
        "executions": outcome.executions,
        "evidence_digests": list(answer.source_digests),
        "read_only": True,
        "fixture_data": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="GA-20 experimental Linux-only Agent sandbox")
    parser.add_argument("--domain", choices=tuple(OPERATIONS), required=True)
    parser.add_argument("--question", help="One natural-language request (or interactive prompt)")
    parser.add_argument("--operator-config", type=Path, help="Pinned external package and SQLite data (sandbox only)")
    args = parser.parse_args()
    try:
        question = args.question if args.question is not None else input("用户任务: ")
        question = validated_question(args.domain, question)
        config = ChatCompletionsConfig(
            endpoint=os.environ.get("GA01C_LLM_URL", "http://127.0.0.1:11434/v1/chat/completions"),
            model=os.environ.get("GA01C_LLM_MODEL", "qwen2.5:3b"),
            api_key=os.environ.get("GA01C_LLM_API_KEY", ""),
            timeout_seconds=45.0,
            max_tokens=200,
        )
        result = asyncio.run(ask_once(args.domain, question, config, args.operator_config))
    except (ValueError, RuntimeError, OSError, EOFError) as exc:
        print(f"GA-20 sandbox declined: {exc}", file=sys.stderr)
        return 1
    print(result["answer"])
    print(f"[read-only sandbox; {result['executions']} verified tool observation(s); {result['answer_mode']}; fixture_data={result['fixture_data']}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
