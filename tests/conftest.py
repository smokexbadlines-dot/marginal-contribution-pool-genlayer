"""Work around genlayer-test 0.29.2 removing an open fd-0 file on Windows."""

import atexit
import os
from unittest.mock import patch


if os.name == "nt":
    import gltest.direct.loader as loader

    _original_inject = loader._inject_message_to_fd0
    _original_unlink = os.unlink
    _deferred_paths = []

    def _defer_open_file(path, *args, **kwargs):
        try:
            _original_unlink(path, *args, **kwargs)
        except PermissionError:
            _deferred_paths.append(path)

    def _windows_inject(vm):
        with patch.object(os, "unlink", side_effect=_defer_open_file):
            return _original_inject(vm)

    def _cleanup():
        for path in _deferred_paths:
            try:
                _original_unlink(path)
            except FileNotFoundError:
                pass

    loader._inject_message_to_fd0 = _windows_inject
    atexit.register(_cleanup)
