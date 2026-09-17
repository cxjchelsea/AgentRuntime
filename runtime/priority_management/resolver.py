"""M2-IU3 configurable priority assignment boundary."""

from __future__ import annotations

from collections.abc import Mapping

from runtime.priority_management.definitions import PrioritySubject
from runtime.priority_management.errors import MissingPriorityAssignmentError


class ConfiguredPriorityResolver:
    """Resolve injected kind -> numeric priority configuration.

    The mapping is supplied by Domain / Business configuration. Runtime Core does not
    define medical, reminder, companion, or other business priority names.
    """

    def __init__(self, assignments: Mapping[str, int]) -> None:
        self._assignments = dict(assignments)
        for kind in self._assignments:
            if not kind.strip():
                raise ValueError("priority kind must not be blank")

    def resolve(
        self,
        *,
        subject_id: str,
        kind: str,
        source: str | None = None,
    ) -> PrioritySubject:
        try:
            priority = self._assignments[kind]
        except KeyError as error:
            raise MissingPriorityAssignmentError(
                "no configured priority for supplied kind"
            ) from error
        return PrioritySubject(
            subject_id=subject_id,
            kind=kind,
            priority=priority,
            source=source,
        )
