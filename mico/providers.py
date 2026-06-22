class FakeModelClient:
    """Deterministic model client for the v0 demo and tests."""

    def __init__(self, outputs=None):
        self.outputs = list(outputs) if outputs is not None else None
        self.prompts = []

    def complete(self, prompt, *_args, **_kwargs):
        self.prompts.append(prompt)
        if self.outputs is not None:
            if not self.outputs:
                raise RuntimeError("fake model ran out of outputs")
            return self.outputs.pop(0)
        if "Tool result from" in prompt:
            return "<final>mico inspected the workspace and completed the request.</final>"
        return '<tool>{"name":"list_files","args":{"path":"."}}</tool>'
