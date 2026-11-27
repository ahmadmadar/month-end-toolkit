"""The one error type the tool raises on purpose.

Messages are written in plain English for the person running the month, so
run.py can print them as-is without a traceback.
"""


class ToolkitError(Exception):
    """A problem the person running the tool can fix (missing file, bad month, no key)."""
