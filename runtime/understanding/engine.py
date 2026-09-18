"""M3-IU5 composed UnderstandingEngine implementation.

The engine composes deterministic parsing, path routing, optional deep-model
inference, IU4 postprocessing, and final Canonical assembly. It remains strictly
inside M3 Understanding authority.
"""

from __future__ import annotations

from runtime.contracts import RuntimeContext, RuntimeInput, UnderstandingState
from runtime.interfaces import UnderstandingEngine
from runtime.understanding.assembly import UnderstandingStateAssembler
from runtime.understanding.deterministic import DeterministicRuleParser
from runtime.understanding.errors import (
    MissingUnderstandingModelError,
    UnderstandingModelExecutionError,
)
from runtime.understanding.model_boundary import (
    DeepUnderstandingRequestBuilder,
    ModelUnderstandingOutputValidator,
    ModelUnderstandingResult,
    StructuredUnderstandingModel,
)
from runtime.understanding.postprocessing import UnderstandingPostprocessor
from runtime.understanding.routing import UnderstandingPathRouter


class RuntimeUnderstandingEngine(UnderstandingEngine):
    """Concrete M3 engine with injected mechanisms and no downstream authority."""

    def __init__(
        self,
        *,
        rule_parser: DeterministicRuleParser,
        path_router: UnderstandingPathRouter,
        request_builder: DeepUnderstandingRequestBuilder,
        output_validator: ModelUnderstandingOutputValidator,
        postprocessor: UnderstandingPostprocessor,
        assembler: UnderstandingStateAssembler,
        model: StructuredUnderstandingModel | None = None,
    ) -> None:
        self._rule_parser = rule_parser
        self._path_router = path_router
        self._request_builder = request_builder
        self._output_validator = output_validator
        self._postprocessor = postprocessor
        self._assembler = assembler
        self._model = model

    async def understand(
        self,
        runtime_input: RuntimeInput,
        runtime_context: RuntimeContext,
    ) -> UnderstandingState:
        rule_result = self._rule_parser.parse(runtime_input, runtime_context)
        route = self._path_router.route(rule_result)

        model_result: ModelUnderstandingResult | None = None
        if route.requires_model:
            if self._model is None:
                raise MissingUnderstandingModelError(
                    "model-required understanding route has no configured model"
                )

            request = self._request_builder.build(
                runtime_input,
                runtime_context,
                route,
            )
            try:
                raw_model_result = await self._model.infer(request)
            except Exception as exc:
                raise UnderstandingModelExecutionError(
                    "deep understanding model execution failed"
                ) from exc

            model_result = self._output_validator.validate(raw_model_result)

        postprocess = self._postprocessor.process(route, model_result)

        return self._assembler.assemble(
            runtime_input,
            route,
            model_result,
            postprocess,
        )
