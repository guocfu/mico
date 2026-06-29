from mico.prompt import PromptBuilder, PromptBundle


def _sample_catalog():
    return [
        {
            "name": "list_files",
            "description": "List files in the workspace.",
            "schema": '{"path": "str=."}',
            "requires_approval": False,
            "read_only": True,
            "concurrency_safe": True,
            "max_result_chars": 4000,
            "allowed": True,
            "approval_note": "always allowed",
        },
        {
            "name": "patch_file",
            "description": "Exact text replacement in a file.",
            "schema": '{"path": "str", "old_text": "str", "new_text": "str"}',
            "requires_approval": True,
            "read_only": False,
            "concurrency_safe": False,
            "max_result_chars": 4000,
            "allowed": False,
            "approval_note": "blocked under approval=never",
        },
    ]


def test_prompt_bundle_is_dataclass():
    bundle = PromptBundle(text="hello", metadata={"k": "v"})
    assert bundle.text == "hello"
    assert bundle.metadata == {"k": "v"}


def test_prompt_builder_returns_bundle():
    builder = PromptBuilder()
    bundle = builder.build(
        tool_catalog=_sample_catalog(),
        approval_policy="never",
        workspace_root="/tmp/ws",
        user_message="inspect files",
        history=[],
    )
    assert isinstance(bundle, PromptBundle)
    assert isinstance(bundle.text, str)
    assert isinstance(bundle.metadata, dict)


def test_prompt_contains_sections():
    builder = PromptBuilder()
    bundle = builder.build(
        tool_catalog=_sample_catalog(),
        approval_policy="never",
        workspace_root="/tmp/ws",
        user_message="inspect files",
        history=[],
    )
    text = bundle.text
    assert "You are mico" in text
    assert "<tool>" in text
    assert "<final>" in text
    assert "Approval policy: never" in text
    assert "Available tools:" in text
    assert "list_files" in text
    assert "patch_file" in text
    assert "not allowed under approval=never" in text
    assert "Workspace: /tmp/ws" in text
    assert "User request: inspect files" in text
    assert "Recent history:" in text


def test_prompt_contract_warns_to_finish_after_successful_edit():
    builder = PromptBuilder()
    bundle = builder.build(
        tool_catalog=_sample_catalog(),
        approval_policy="auto",
        workspace_root="/tmp/ws",
        user_message="inspect files",
        history=[],
    )

    assert "After creating or editing a file, do not repeat or refine the same operation." in bundle.text
    assert "When the requested change is complete, respond with <final> immediately." in bundle.text


def test_prompt_empty_history_shows_empty():
    builder = PromptBuilder()
    bundle = builder.build(
        tool_catalog=_sample_catalog(),
        approval_policy="auto",
        workspace_root="/tmp/ws",
        user_message="hello",
        history=[],
    )
    assert "(empty)" in bundle.text


def test_prompt_with_history():
    builder = PromptBuilder()
    history = [
        {"role": "user", "content": "list files"},
        {"role": "assistant", "content": "I listed them."},
        {"role": "tool", "name": "list_files", "content": "[F] a.txt"},
    ]
    bundle = builder.build(
        tool_catalog=_sample_catalog(),
        approval_policy="auto",
        workspace_root="/tmp/ws",
        user_message="read a.txt",
        history=history,
    )
    text = bundle.text
    assert "user: list files" in text
    assert "assistant: I listed them." in text
    assert "Tool result from list_files: [F] a.txt" in text


def test_prompt_history_limited_to_six():
    builder = PromptBuilder()
    history = [{"role": "user", "content": f"msg{i}"} for i in range(10)]
    bundle = builder.build(
        tool_catalog=_sample_catalog(),
        approval_policy="auto",
        workspace_root="/tmp/ws",
        user_message="hello",
        history=history,
    )
    assert "msg9" in bundle.text
    assert "msg4" in bundle.text
    assert "msg3" not in bundle.text
    assert "msg2" not in bundle.text


def test_prompt_metadata_fields():
    builder = PromptBuilder()
    history = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    bundle = builder.build(
        tool_catalog=_sample_catalog(),
        approval_policy="never",
        workspace_root="/tmp/ws",
        user_message="do something",
        history=history,
    )
    meta = bundle.metadata
    assert meta["prompt_chars"] == len(bundle.text)
    assert meta["history_items_total"] == 2
    assert meta["history_items_used"] == 2
    assert meta["tool_count"] == 2
    assert meta["restricted_tool_count"] == 1
    assert meta["approval_policy"] == "never"
    assert meta["current_request_chars"] == len("do something")


def test_prompt_metadata_empty_history():
    builder = PromptBuilder()
    bundle = builder.build(
        tool_catalog=_sample_catalog(),
        approval_policy="auto",
        workspace_root="/tmp/ws",
        user_message="hello",
        history=[],
    )
    meta = bundle.metadata
    assert meta["history_items_total"] == 0
    assert meta["history_items_used"] == 0


def test_prompt_metadata_approval_never_restricts_patch():
    builder = PromptBuilder()
    catalog = _sample_catalog()
    bundle = builder.build(
        tool_catalog=catalog,
        approval_policy="never",
        workspace_root="/tmp/ws",
        user_message="fix code",
        history=[],
    )
    assert "patch_file" in bundle.text
    assert "not allowed under approval=never" in bundle.text
    assert bundle.metadata["restricted_tool_count"] == 1


def test_prompt_contains_os_info():
    import sys
    builder = PromptBuilder()
    bundle = builder.build(
        tool_catalog=_sample_catalog(),
        approval_policy="auto",
        workspace_root="/tmp/ws",
        user_message="hello",
        history=[],
    )
    assert "OS:" in bundle.text
    assert sys.platform in bundle.text


def test_prompt_contains_available_shells():
    from mico.prompt import detect_available_shells
    builder = PromptBuilder()
    bundle = builder.build(
        tool_catalog=_sample_catalog(),
        approval_policy="auto",
        workspace_root="/tmp/ws",
        user_message="hello",
        history=[],
    )
    assert "Available shells:" in bundle.text
    available = detect_available_shells()
    if available:
        for shell in available:
            assert shell in bundle.text
    else:
        assert "(none detected)" in bundle.text


def test_prompt_contains_shell_guidance():
    builder = PromptBuilder()
    bundle = builder.build(
        tool_catalog=_sample_catalog(),
        approval_policy="auto",
        workspace_root="/tmp/ws",
        user_message="hello",
        history=[],
    )
    assert "Guidance:" in bundle.text
    assert "OS" in bundle.text


def test_prompt_warns_not_to_repeat_successful_write_tools():
    builder = PromptBuilder()
    bundle = builder.build(
        tool_catalog=_sample_catalog(),
        approval_policy="auto",
        workspace_root="/tmp/ws",
        user_message="write file",
        history=[
            {"role": "tool", "name": "patch_file", "content": "patched code.py"},
        ],
    )

    assert "After creating or editing a file, do not repeat or refine the same operation." in bundle.text
    assert "Do not read or list files solely to inspect your own edit." in bundle.text
    assert "When the requested change is complete, respond with <final> immediately." in bundle.text


def test_prompt_uses_completion_behavior_not_same_arguments_rule():
    builder = PromptBuilder()
    bundle = builder.build(
        tool_catalog=_sample_catalog(),
        approval_policy="auto",
        workspace_root="/tmp/ws",
        user_message="fix code",
        history=[],
    )
    assert "After creating or editing a file, do not repeat or refine the same operation." in bundle.text
    assert "Do not repeat the same tool call with the same arguments" not in bundle.text


def test_prompt_does_not_contain_old_long_reminders():
    builder = PromptBuilder()
    bundle = builder.build(
        tool_catalog=_sample_catalog(),
        approval_policy="auto",
        workspace_root="/tmp/ws",
        user_message="fix code",
        history=[
            {"role": "tool", "name": "patch_file", "content": "patched code.py"},
        ],
    )
    assert "If you need confidence" not in bundle.text
    assert "successful patch_file or write_file" not in bundle.text
    assert "do not call the same write again" not in bundle.text


def test_detect_available_shells_returns_list():
    from mico.prompt import detect_available_shells
    result = detect_available_shells()
    assert isinstance(result, list)
    # Every entry is a string from the known set
    from mico.prompt import _SHELL_NAMES
    for name in result:
        assert name in _SHELL_NAMES


# --- Task 1: Section factory tests ---

def test_prompt_current_request_is_last_section():
    """User request must be the last section in the prompt."""
    builder = PromptBuilder()
    bundle = builder.build(
        tool_catalog=_sample_catalog(),
        approval_policy="auto",
        workspace_root="/tmp/ws",
        user_message="inspect files",
        history=[{"role": "user", "content": "prev"}],
    )
    text = bundle.text.strip()
    assert text.endswith("User request: inspect files"), f"Prompt does not end with current request, ends with: ...{text[-100:]}"


def test_prompt_format_reminder_before_current_request():
    """Format reminder must appear before current request, not after."""
    builder = PromptBuilder()
    bundle = builder.build(
        tool_catalog=_sample_catalog(),
        approval_policy="auto",
        workspace_root="/tmp/ws",
        user_message="inspect files",
        history=[],
    )
    text = bundle.text
    reminder_pos = text.find("Reminder:")
    request_pos = text.find("User request:")
    assert reminder_pos >= 0, "Reminder not found"
    assert request_pos >= 0, "User request not found"
    assert reminder_pos < request_pos, f"Reminder (pos {reminder_pos}) should be before User request (pos {request_pos})"


def test_prompt_builder_has_prefix_text_method():
    """PromptBuilder should expose prefix_text as a section factory method."""
    builder = PromptBuilder()
    text = builder.prefix_text(
        tool_catalog=_sample_catalog(),
        approval_policy="auto",
        workspace_root="/tmp/ws",
    )
    assert isinstance(text, str)
    assert "You are mico" in text
    assert "Reminder:" in text  # format_reminder is in prefix


def test_prompt_builder_has_history_text_method():
    """PromptBuilder should expose history_text as a section factory method."""
    builder = PromptBuilder()
    history = [{"role": "user", "content": "hi"}]
    text = builder.history_text(history)
    assert isinstance(text, str)
    assert "user: hi" in text


def test_prompt_builder_has_current_request_text_method():
    """PromptBuilder should expose current_request_text as a section factory method."""
    builder = PromptBuilder()
    text = builder.current_request_text("do something")
    assert isinstance(text, str)
    assert "User request: do something" in text
