"""
pytest configuration.

onnxruntime (pulled in by chromadb's default embedding function) occasionally aborts
inside native destructors during interpreter teardown ("recursive_mutex lock failed"),
turning a fully green run into exit code 134. Exit directly once pytest has finished
printing its summary so the real test result is what CI sees.
"""
import os
import sys


def pytest_sessionfinish(session, exitstatus):
    session.config._final_exitstatus = int(exitstatus)


def pytest_unconfigure(config):
    status = getattr(config, "_final_exitstatus", None)
    if status is None:
        return
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(status)
