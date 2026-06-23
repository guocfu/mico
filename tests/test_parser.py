from mico.parser import ModelOutputParser, ParsedModelOutput


class TestModelOutputParser:
    def setup_method(self):
        self.parser = ModelOutputParser()

    def test_parse_valid_tool_json(self):
        result = self.parser.parse('<tool>{"name":"list_files","args":{"path":"."}}</tool>')

        assert isinstance(result, ParsedModelOutput)
        assert result.kind == "tool"
        assert result.payload["name"] == "list_files"
        assert result.payload["args"]["path"] == "."
        assert result.error_kind is None

    def test_parse_malformed_tool_json(self):
        result = self.parser.parse("<tool>{bad</tool>")

        assert result.kind == "retry"
        assert "malformed tool JSON" in result.payload
        assert result.error_kind == "malformed_tool_json"

    def test_parse_valid_final(self):
        result = self.parser.parse("<final>done</final>")

        assert result.kind == "final"
        assert result.payload == "done"
        assert result.error_kind is None

    def test_parse_empty_final(self):
        result = self.parser.parse("<final>  </final>")

        assert result.kind == "retry"
        assert "empty final" in result.payload
        assert result.error_kind == "empty_final"

    def test_parse_unknown_block(self):
        result = self.parser.parse("some random text")

        assert result.kind == "retry"
        assert "neither <tool> nor <final>" in result.payload
        assert result.error_kind == "unknown_block"

    def test_parse_none_input(self):
        result = self.parser.parse(None)

        assert result.kind == "retry"
        assert result.error_kind == "unknown_block"

    def test_parse_empty_string(self):
        result = self.parser.parse("")

        assert result.kind == "retry"
        assert result.error_kind == "unknown_block"
