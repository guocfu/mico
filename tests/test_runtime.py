from mico.runtime import Mico


def test_parse_tool_json():
    kind, payload = Mico.parse('<tool>{"name":"list_files","args":{"path":"."}}</tool>')

    assert kind == "tool"
    assert payload["name"] == "list_files"


def test_parse_final():
    assert Mico.parse("<final>done</final>") == ("final", "done")


def test_parse_bad_tool_json_retries():
    kind, payload = Mico.parse("<tool>{bad</tool>")

    assert kind == "retry"
    assert "malformed tool JSON" in payload
