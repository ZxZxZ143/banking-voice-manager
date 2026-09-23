"""Starter-kit action definitions and extension points for future handlers."""

from app.tools.actions import ToolResult
from app.tools.errors import ToolError
from app.tools.registry import ActionRegistry

__all__ = ["ActionRegistry", "ToolError", "ToolResult"]
