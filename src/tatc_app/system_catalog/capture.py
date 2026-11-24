"""
Capture of the warnings with which the TAT-C library's catalog
(`tatc.catalog`) reports what it does not validate, while building systems
and instruments from it.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import contextlib
import threading
import warnings
from typing import Iterator, List

# `warnings.catch_warnings` is not thread-safe, so builds are serialized
_BUILD_LOCK = threading.Lock()


@contextlib.contextmanager
def capture_catalog_warnings(notes: List[str]) -> Iterator[None]:
    """
    Context in which to build from the catalog: builds run one at a time, and
    the messages of warnings raised within the context are appended to notes
    when it exits.

    Args:
        notes (List[str]): The notes to append warning messages to.
    """
    with _BUILD_LOCK, warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        yield
    notes.extend(str(warning.message) for warning in caught)
