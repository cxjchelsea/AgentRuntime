"""M1 Input Processing concrete implementations.

This package contains real M1 input normalization logic while keeping
understanding, policy, planning, execution, and Domain semantics out of M1.
"""

from runtime.input_processing.errors import InputNormalizationError
from runtime.input_processing.processor import DefaultInputProcessor

__all__ = ["DefaultInputProcessor", "InputNormalizationError"]
