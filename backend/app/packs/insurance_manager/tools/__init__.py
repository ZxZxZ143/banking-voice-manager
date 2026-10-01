"""Starter-kit action definitions and extension points for future handlers."""

from app.packs.insurance_manager.tools.actions import ToolResult
from app.packs.insurance_manager.tools.errors import ToolError
from app.packs.insurance_manager.tools.registry import ActionRegistry

__all__ = ["ActionRegistry", "ToolError", "ToolResult"]
