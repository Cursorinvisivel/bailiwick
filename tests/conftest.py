"""Shared pytest setup: put hooks/ on sys.path once, explicitly.

The hook modules import their shared substrate as a sibling (``import bw_common`` — resolved in
production via sys.path[0], since hooks are invoked by absolute path). Test modules that import
hooks directly, and the white-box fixture in test_guardrails.py that loads via
importlib.spec_from_file_location, both need the same resolution — previously that only worked
by accident of one test module's process-wide sys.path insert and alphabetical collection order.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "hooks"))
