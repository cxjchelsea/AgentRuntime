"""M2-IU3 ConfiguredPriorityResolver tests."""

import pytest

from runtime.priority_management import (
    ConfiguredPriorityResolver,
    MissingPriorityAssignmentError,
)


def test_priority_resolver_uses_only_injected_assignments() -> None:
    resolver = ConfiguredPriorityResolver(
        {
            "TEST_LOW": 10,
            "TEST_HIGH": 90,
        }
    )

    low = resolver.resolve(subject_id="low", kind="TEST_LOW", source="TEST")
    high = resolver.resolve(subject_id="high", kind="TEST_HIGH", source="TEST")

    assert low.priority == 10
    assert high.priority == 90
    assert low.kind == "TEST_LOW"
    assert high.kind == "TEST_HIGH"


def test_missing_priority_assignment_fails_instead_of_guessing() -> None:
    resolver = ConfiguredPriorityResolver({"TEST_DEFINED": 1})

    with pytest.raises(MissingPriorityAssignmentError):
        resolver.resolve(subject_id="event", kind="TEST_UNKNOWN")


def test_blank_priority_kind_is_rejected_at_configuration_time() -> None:
    with pytest.raises(ValueError, match="must not be blank"):
        ConfiguredPriorityResolver({" ": 1})
