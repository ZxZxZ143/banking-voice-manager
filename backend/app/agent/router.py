"""Compatibility module alias, including existing SDK test injection points."""

import sys

from app.packs.insurance_manager.agent import router as _implementation

sys.modules[__name__] = _implementation
