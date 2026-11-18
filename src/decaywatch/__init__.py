"""decaywatch — measure how much of a collected dataset is still there."""

from decaywatch.common import RESULT_SCHEMA_VERSION, ToolResult
from decaywatch.logic import DecayWatchLogic, run

__version__ = "0.2.0"
__all__ = [
    "RESULT_SCHEMA_VERSION",
    "DecayWatchLogic",
    "ToolResult",
    "__version__",
    "run",
]
