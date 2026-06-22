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


class OpenAICompatibleModelClient:
    """Model client that calls an OpenAI-compatible chat/completions endpoint."""

    def __init__(self, base_url, model, api_key, timeout=120):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = api_key
        self.timeout = timeout
        self.prompts = []

    @classmethod
    def from_env(cls, base_url, model, api_key_env="MICO_API_KEY", timeout=120):
        import os

        api_key = os.environ.get(api_key_env, "")
        if not api_key:
            raise ValueError(
                f"API key not found. Set the {api_key_env} environment variable."
            )
        return cls(base_url=base_url, model=model, api_key=api_key, timeout=timeout)

    def complete(self, prompt, *_args, **_kwargs):
        import json
        import urllib.request
        import urllib.error

        self.prompts.append(prompt)
        url = f"{self.base_url}/chat/completions"
        payload = json.dumps(
            {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"model request failed: {exc}") from exc

        try:
            return body["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise RuntimeError(f"unexpected model response format: {body}") from exc
