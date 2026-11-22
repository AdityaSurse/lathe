"""Alias entry point for orchestrator agent tests."""

from tests.orchestrator.test_agent import (
    ScriptedFakeLLMClient,
    test_agent_fallback_tool_protocol,
    test_agent_full_edit_and_test_integration,
    test_agent_loop_detection_nudge_and_stop,
    test_agent_max_steps_limit,
    test_agent_parallel_read_tools,
    test_cli_one_shot_routing,
    test_terminal_agent_ui_rendering,
    test_workspace,
)

__all__ = [
    "ScriptedFakeLLMClient",
    "test_agent_fallback_tool_protocol",
    "test_agent_full_edit_and_test_integration",
    "test_agent_loop_detection_nudge_and_stop",
    "test_agent_max_steps_limit",
    "test_agent_parallel_read_tools",
    "test_cli_one_shot_routing",
    "test_terminal_agent_ui_rendering",
    "test_workspace",
]
