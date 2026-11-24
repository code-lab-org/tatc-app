"""
Capture of the warnings with which the TAT-C library's catalog
(`tatc.catalog`) reports what it does not validate.

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
    Builds from the catalog (one build at a time), appending the messages of
    warnings raised by the build to notes.

    Args:
        notes (List[str]): The notes to append warning messages to.
    """
    with _BUILD_LOCK, warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        yield
    notes.extend(str(warning.message) for warning in caught)
