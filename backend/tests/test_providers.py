"""1.8 add-on — cloud language models: encrypted API keys, how each provider is driven, and how calls are routed.

No test talks to a real provider: the keys are made-up strings and the network is replaced by stand-ins.
"""
import json

import httpx
import pytest

from app import app_settings, estimate, history, llm, providers, vault
from app.models import GenerateRequest
from conftest import make_project

CLAUDE_KEY = "sk-ant-" + "made-up-for-tests-" + "0001"
GPT_KEY = "sk-" + "made-up-for-tests-" + "0002"
NVIDIA_KEY = "nvapi-" + "made-up-for-tests-" + "0003"


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    """Every test starts and ends without keys, learned rules or a team."""
    def wipe():
        providers.PATH.unlink(missing_ok=True)
        providers._secrets.clear(), providers._learned.clear(), providers._stats.clear()
        app_settings.PATH.unlink(missing_ok=True)
        app_settings._tokens.clear()
    wipe()
    monkeypatch.setattr(llm, "runtime", llm._Runtime())
    monkeypatch.setattr(providers, "_models", lambda record, secret: [record["model"], "another-model"])   # "the provider accepts the key"
    yield
    wipe()


def add(key, **kw):
    return providers.add_key({"key": key, **kw})


# ------------------------------------------------------------------ the vault and the key store
def test_secrets_are_encrypted_and_only_readable_through_the_vault():
    sealed = vault.seal(CLAUDE_KEY)
    assert CLAUDE_KEY not in sealed and "made-up" not in sealed and vault.unseal(sealed) == CLAUDE_KEY
    assert vault.seal(CLAUDE_KEY) != sealed or sealed.startswith("fernet:") is False     # DPAPI salts every seal
    for broken in ("dpapi:AAAA", "fernet:AAAA", "plain:" + CLAUDE_KEY):
        with pytest.raises(ValueError):
            vault.unseal(broken)


def test_keys_are_saved_encrypted_and_never_shown_again(client):
    out = client.post("/api/settings/llm/keys", json={"key": CLAUDE_KEY, "label": "Lab account"}).json()
    key = out["keys"][0]
    assert key["provider"] == "anthropic" and key["name"] == "Claude" and key["model"] == "claude-opus-5-5"       # told from how the key starts
    assert key["tail"] == "0001" and key["status"] == "ok" and key["parallel"] == 2 and key["enabled"] is True
    assert "Windows" in out["protection"] or "AES" in out["protection"]
    on_disk = providers.PATH.read_text(encoding="utf-8")
    for place in (json.dumps(out), on_disk, json.dumps(client.get("/api/settings/llm/keys").json()), json.dumps(client.get("/api/health").json())):
        assert CLAUDE_KEY not in place and "made-up-for-tests" not in place
    assert providers._secret(providers._record(key["id"])) == CLAUDE_KEY                                           # … but RAF itself can use it

    assert "already saved" in client.post("/api/settings/llm/keys", json={"key": CLAUDE_KEY}).json()["detail"]
    client.post("/api/settings/llm/keys", json={"key": CLAUDE_KEY, "model": "claude-haiku-5-5", "role": "checks"})    # the same key for a second model is fine
    client.post("/api/settings/llm/keys", json={"key": NVIDIA_KEY, "parallel": 9})
    keys = client.get("/api/settings/llm/keys").json()["keys"]
    assert [k["provider"] for k in keys] == ["anthropic", "anthropic", "nvidia"] and keys[2]["parallel"] == 4 and keys[1]["role"] == "checks"

    for bad, why in (({"key": "short"}, "does not look like"), ({"key": "no-known-prefix-" + "x" * 12}, "which provider"),
                     ({"key": GPT_KEY, "provider": "custom"}, "address of the server"),
                     ({"key": GPT_KEY, "provider": "custom", "base_url": "http://example.org/v1", "model": "m"}, "https://")):
        r = client.post("/api/settings/llm/keys", json=bad)
        assert r.status_code == 422 and why in r.json()["detail"], bad
    assert client.post("/api/settings/llm/keys", json={"key": GPT_KEY, "provider": "custom", "base_url": "http://localhost:1234/v1", "model": "local-model"}).status_code == 200

    kid = keys[2]["id"]
    changed = client.patch(f"/api/settings/llm/keys/{kid}", json={"model": "another-model", "enabled": False, "parallel": 1}).json()["keys"][2]
    assert changed["model"] == "another-model" and changed["enabled"] is False and changed["parallel"] == 1
    order = [k["id"] for k in client.put("/api/settings/llm/keys-order", json={"order": [kid]}).json()["keys"]]
    assert order[0] == kid and len(order) == 4
    assert client.get(f"/api/settings/llm/keys/{kid}/models").json()["models"] == ["another-model", "another-model"]
    assert client.delete(f"/api/settings/llm/keys/{kid}").status_code == 200 and client.delete(f"/api/settings/llm/keys/{kid}").status_code == 404
    assert client.put("/api/settings/llm/mode?mode=cloud").json()["mode"] == "cloud" and client.put("/api/settings/llm/mode?mode=moon").status_code == 422


def test_a_key_the_provider_rejects_is_not_stored_and_the_lock_guards_the_keys(client, monkeypatch):
    def rejected(record, secret):
        raise providers.ProviderError("auth", f"HTTP 401: Incorrect API key provided: {secret}")
    monkeypatch.setattr(providers, "_models", rejected)
    r = client.post("/api/settings/llm/keys", json={"key": GPT_KEY})
    assert r.status_code == 422 and "did not accept this key" in r.json()["detail"] and client.get("/api/settings/llm/keys").json()["keys"] == []

    def offline(record, secret):
        raise providers.ProviderError("busy", "could not reach OpenAI (ConnectError)")
    monkeypatch.setattr(providers, "_models", offline)
    saved = client.post("/api/settings/llm/keys", json={"key": GPT_KEY}).json()["keys"][0]                # no network: saved, to be tested later
    assert saved["status"] == "unchecked" and "Could not reach" in saved["note"]

    code = "test-" + "passcode"
    token = client.put("/api/settings/admin/passcode", json={"passcode": code}).json()["token"]
    for call in (lambda h: client.post("/api/settings/llm/keys", json={"key": NVIDIA_KEY}, headers=h),
                 lambda h: client.patch(f"/api/settings/llm/keys/{saved['id']}", json={"enabled": False}, headers=h),
                 lambda h: client.post(f"/api/settings/llm/keys/{saved['id']}/test", headers=h),
                 lambda h: client.get(f"/api/settings/llm/keys/{saved['id']}/models", headers=h),
                 lambda h: client.put("/api/settings/llm/mode?mode=local", headers=h),
                 lambda h: client.delete(f"/api/settings/llm/keys/{saved['id']}", headers=h)):
        assert call({}).status_code == 401                                                                 # locked: nothing can be changed or used
    assert client.get("/api/settings/llm/keys").status_code == 200                                          # the masked list stays readable
    assert client.delete(f"/api/settings/llm/keys/{saved['id']}", headers={"X-RAF-Admin": token}).status_code == 200


# ------------------------------------------------------------------ how each provider is driven
class FakeServer:
    """An OpenAI-compatible server that rejects what a reasoning model rejects, then answers."""

    def __init__(self, reject=("max_tokens", "temperature")):
        self.reject, self.bodies, self.headers = list(reject), [], []

    def answer(self, url, headers, body):
        self.bodies.append(body)
        self.headers.append(headers)
        for name in self.reject:
            if name in body:
                extra = " Use 'max_completion_tokens' instead." if name == "max_tokens" else ""
                return 400, json.dumps({"error": {"message": f"Unsupported parameter: '{name}' is not supported with this model.{extra}"}})
        return 200, None

    def client(server, **kw):          # noqa: N805 - used as httpx.Client
        class Stream:
            def __init__(self, status, text, lines):
                self.status_code, self.text, self.lines, self.headers = status, text, lines, {}

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return (self.text or "").encode()

            def iter_lines(self):
                yield from self.lines

            def json(self):
                return {"choices": [{"message": {"content": '{"ok": true}'}}]}

        class Client:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def post(self, url, headers=None, json=None):
                status, text = server.answer(url, headers, json)
                return Stream(status, text, [])

            def stream(self, method, url, headers=None, json=None):
                status, text = server.answer(url, headers, json)
                lines = [f'data: {{"choices": [{{"delta": {{"content": "{piece}"}}}}]}}' for piece in ("Small ", "firms ", "grow.")] + ["data: [DONE]"]
                return Stream(status, text, lines)
        return Client()


def test_openai_style_models_learn_which_parameters_they_take(monkeypatch):
    server = FakeServer()
    monkeypatch.setattr(providers.httpx, "Client", server.client)
    kid = add(GPT_KEY)["id"]
    got = []
    messages = [{"role": "system", "content": "You write scholarly prose."}, {"role": "user", "content": "Write one sentence."}]
    assert providers.call(kid, messages, temperature=0.7, max_tokens=500, sink=got.append) == "Small firms grow." and got == ["Small ", "firms ", "grow."]
    first, last = server.bodies[0], server.bodies[-1]
    assert len(server.bodies) == 3 and first["max_tokens"] == 4500 and first["temperature"] == 0.7                 # 4,000 tokens of room for reasoning
    assert "max_tokens" not in last and "temperature" not in last and last["max_completion_tokens"] == 4500 and last["stream"] is True
    assert server.headers[0] == {"Authorization": f"Bearer {GPT_KEY}"}
    assert last["messages"][0]["role"] == "system" and "You write scholarly prose." in last["messages"][0]["content"] and "Output contract" in last["messages"][0]["content"]
    assert providers._learned[("openai", "gpt-5")] == {"max_completion_tokens", "no_temperature"}

    assert providers.call(kid, messages, temperature=0.2, max_tokens=300, json_mode=True) == '{"ok": true}'          # the rules are remembered: one request
    body = server.bodies[-1]
    assert len(server.bodies) == 4 and body["response_format"] == {"type": "json_object"} and "max_tokens" not in body and "stream" not in body
    assert "one valid JSON value" in body["messages"][0]["content"] and "Output contract" not in body["messages"][0]["content"]
    assert providers.list_keys()[0]["usage"]["calls"] == 2


def test_provider_errors_are_sorted_and_never_repeat_the_key(monkeypatch):
    kid = add(GPT_KEY)["id"]
    for status, body, kind in ((401, f"Incorrect API key provided: {GPT_KEY}", "auth"), (429, "Rate limit reached", "rate"),
                               (429, "You exceeded your current quota, please check your plan and billing details", "quota"),
                               (503, "overloaded", "busy"), (404, "The model does not exist", "bad")):
        class Client:
            def __init__(self, **kw):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def post(self, url, headers=None, json=None, status=status, body=body):
                return type("R", (), {"status_code": status, "text": json_dumps({"error": {"message": body}}), "headers": {"retry-after": "7"}})()
        json_dumps = json.dumps
        monkeypatch.setattr(providers.httpx, "Client", Client)
        with pytest.raises(providers.ProviderError) as err:
            providers.call(kid, [{"role": "user", "content": "x"}], temperature=0.1, max_tokens=10)
        assert err.value.kind == kind and GPT_KEY not in str(err.value) and "made-up" not in str(err.value)
        assert err.value.retry_after == (7 if kind == "rate" else None)
    assert providers.list_keys()[0]["usage"]["errors"] == 5 and GPT_KEY not in json.dumps(providers.list_keys())


def test_claude_is_called_through_its_sdk_with_its_own_rules(monkeypatch):
    import anthropic
    import httpx2

    seen = []

    class Final:
        stop_reason = "end_turn"
        content = [type("B", (), {"type": "thinking", "thinking": ""})(), type("B", (), {"type": "text", "text": "Small firms grow."})()]

    class Stream:
        def __init__(self, final=Final):
            self.final = final

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        @property
        def text_stream(self):
            yield from ("Small ", "firms ", "grow.")

        def get_final_message(self):
            return self.final

    def problem(cls, status, message):
        return cls(message, response=httpx2.Response(status, request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")), body=None)

    class Messages:
        def __init__(self, beta):
            self.beta = beta

        def stream(self, **params):
            seen.append({"beta": self.beta, **params})
            if self.beta and "fallbacks" in params and behaviour == "no fallback":
                raise problem(anthropic.BadRequestError, 400, "fallbacks: unknown beta feature")
            if "output_config" in params and behaviour == "old model":
                raise problem(anthropic.BadRequestError, 400, "output_config.effort is not supported on this model")
            if behaviour == "refuses":
                return Stream(type("F", (), {"stop_reason": "refusal", "content": []}))
            if behaviour == "bad key":
                raise problem(anthropic.AuthenticationError, 401, "invalid x-api-key")
            return Stream()

    class Client:
        def __init__(self, **kw):
            created.append(kw)
            self.messages = Messages(False)
            self.beta = type("Beta", (), {"messages": Messages(True)})()

    created: list = []
    monkeypatch.setattr(anthropic, "Anthropic", Client)
    kid = add(CLAUDE_KEY)["id"]
    messages = [{"role": "system", "content": "You write scholarly prose."}, {"role": "user", "content": "Write one sentence."}]

    behaviour, got = "normal", []
    assert providers.call(kid, messages, temperature=0.9, max_tokens=800, sink=got.append) == "Small firms grow." and got == ["Small ", "firms ", "grow."]
    sent = seen[-1]
    assert created[-1]["api_key"] == CLAUDE_KEY and created[-1]["max_retries"] == 1
    assert sent["model"] == "claude-opus-5-5" and sent["max_tokens"] == 6800 and sent["output_config"] == {"effort": "medium"}
    assert sent["messages"] == [{"role": "user", "content": "Write one sentence."}] and sent["system"].startswith("You write scholarly prose.") and "Output contract" in sent["system"]
    assert not {"temperature", "top_p", "thinking"} & set(sent)                                              # current Claude models reject sampling; thinking stays adaptive
    assert sent["beta"] is True and sent["fallbacks"] == "default" and sent["betas"] == ["server-side-fallback-2026-07-01"]

    providers.call(kid, messages, temperature=0.2, max_tokens=300, json_mode=True)
    assert seen[-1]["output_config"] == {"effort": "low"} and "one valid JSON value" in seen[-1]["system"]

    behaviour = "no fallback"                                                                                 # a rejected extra is dropped, and remembered
    assert providers.call(kid, messages, temperature=0.5, max_tokens=100) == "Small firms grow."
    assert seen[-1]["beta"] is False and "fallbacks" not in seen[-1] and "fallbacks" in providers._learned[("anthropic", "claude-opus-5-5")]

    providers.update_key(kid, {"model": "claude-haiku-4-5"})
    behaviour = "old model"
    assert providers.call(kid, messages, temperature=0.5, max_tokens=100) == "Small firms grow."
    assert "output_config" not in seen[-1] and seen[-1]["beta"] is False and providers._learned[("anthropic", "claude-haiku-4-5")] == {"effort"}

    for behaviour, kind in (("refuses", "refused"), ("bad key", "auth")):
        with pytest.raises(providers.ProviderError) as err:
            providers.call(kid, messages, temperature=0.5, max_tokens=100)
        assert err.value.kind == kind


# ------------------------------------------------------------------ routing
@pytest.fixture
def engines(monkeypatch):
    """Replace both ends: cloud calls answer by key, the local model answers 'local'. `plan[key id]` can hold an error to raise."""
    plan, calls = {}, []

    def cloud(kid, messages, **kw):
        calls.append((kid, "json" if kw.get("json_mode") else "prose"))
        if plan.get(kid):
            raise plan[kid]
        return f"from {kid}"

    def local(client, payload, sink):
        calls.append(("local", "json" if payload.get("format") else "prose"))
        if plan.get("local"):
            raise plan["local"]
        return 200, "from local"
    monkeypatch.setattr(providers, "call", cloud)
    monkeypatch.setattr(llm, "_post", local)
    monkeypatch.setattr(llm, "wait_for_ollama", lambda seconds: False)
    return plan, calls


def test_cloud_keys_become_extra_agents_and_failures_move_the_work(engines):
    plan, calls = engines
    logged = []
    a, b = add(CLAUDE_KEY)["id"], add(NVIDIA_KEY, parallel=3)["id"]
    llm.runtime.configure(2, notify=logged.append)
    assert llm.runtime.capacity == 7 and [(e["id"], e["agents"], e["local"]) for e in llm.runtime.team()] == [(a, 2, False), (b, 3, False), ("local", 2, True)]
    assert llm.generate("s", "p") == f"from {a}"                                   # the first key in the list goes first

    plan[a] = providers.ProviderError("rate", "HTTP 429: slow down", 30)
    assert llm.generate("s", "p") == f"from {b}" and any("rate limit" in m and "30 s" in m for m in logged)
    assert llm.generate("s", "p") == f"from {b}" and calls.count((a, "prose")) == 2   # the limited key rests: it is not asked again

    plan[b] = providers.ProviderError("auth", "HTTP 401: invalid key")
    assert llm.generate("s", "p") == "from local"                                  # one resting, one rejected: this PC takes over
    assert providers.list_keys()[1]["status"] == "rejected" and any("switched off" in m for m in logged)
    assert [e["id"] for e in llm.runtime.team()] == [a, "local"] and llm.runtime.capacity == 4

    llm.runtime.configure(1, cloud=False)                                          # a run that leaves the cloud models out
    assert llm.runtime.capacity == 1 and llm.generate("s", "p") == "from local" and [e["id"] for e in llm.runtime.team()] == ["local"]


def test_roles_refusals_and_cloud_only_mode(engines):
    plan, calls = engines
    writer_key, checker = add(CLAUDE_KEY, role="writing")["id"], add(NVIDIA_KEY, role="checks")["id"]
    providers.set_mode("cloud")
    llm.runtime.configure(3)
    assert llm.runtime.capacity == 4 and all(not e["local"] for e in llm.runtime.team())          # this PC is on standby, not part of the team
    llm.generate("s", "p"), llm.generate_json("s", "p", default={})
    assert calls == [(writer_key, "prose"), (checker, "json")]                                      # each key does the kind of work it was given

    plan[writer_key] = providers.ProviderError("refused", "Claude declined this request.")
    assert llm.generate("s", "p") == f"from {checker}"                                              # a declined request goes to another model, role or not
    plan[checker] = providers.ProviderError("refused", "declined")
    assert llm.generate("s", "p") == "from local"                                                   # … and to this PC when every cloud model declined it
    del plan[writer_key], plan[checker]
    assert llm.generate("s", "p") == f"from {writer_key}"                                           # declining one request does not switch a key off

    plan[writer_key] = plan[checker] = providers.ProviderError("auth", "HTTP 401")
    logged = []
    llm.runtime.notify = logged.append
    assert llm.generate("s", "p") == "from local" and any("No cloud model is left" in m for m in logged)
    plan["local"] = httpx.ConnectError("refused")
    with pytest.raises(llm.LLMError):
        llm.generate("s", "p", retries=1)


def test_cloud_models_carry_on_when_this_pc_has_no_model(engines, client, monkeypatch):
    plan, calls = engines
    monkeypatch.setattr(llm.httpx, "get", lambda *a, **kw: (_ for _ in ()).throw(httpx.ConnectError("no ollama")))
    health = client.get("/api/health").json()
    assert health["ollama"] is False and health["ready"] is False and health["cloud"] == {"mode": "hybrid", "engines": [], "agents": 0}
    kid = add(GPT_KEY)["id"]
    health = client.get("/api/health").json()
    assert health["ready"] is True and health["cloud"]["agents"] == 2 and health["cloud"]["engines"][0] == {
        "id": kid, "provider": "openai", "name": "GPT", "label": "", "model": "gpt-5", "parallel": 2, "role": "all"}
    providers.update_key(kid, {"role": "checks"})          # prose would go to this PC first …
    plan["local"] = httpx.ConnectError("no ollama")
    logged = []
    llm.runtime.configure(1, notify=logged.append)
    assert llm.generate("s", "p") == f"from {kid}" and any("local model is not reachable" in m for m in logged)   # … which is not there: the key writes
    assert llm.runtime.capacity == 2 and llm.ready() is True
    providers.set_mode("local")                             # keys kept, but nothing leaves this PC
    assert client.get("/api/health").json()["ready"] is False and providers.engines() == []


def test_the_record_and_the_estimate_know_about_cloud_models(project):
    add(CLAUDE_KEY), add(NVIDIA_KEY, parallel=3)
    llm.runtime.configure(1)
    est = estimate.compute(project, GenerateRequest(segments=["introduction", "discussion"], depth="quick"), ["introduction", "discussion"], {"tok_s": 5.0, "seconds": 1.0, "model": "stub"})
    assert est["lanes"] == 6 and est["cloud_agents"] == 5 and est["speed_source"] == "assumed for cloud models" and est["tok_s"] > 30
    local = estimate.compute(project, GenerateRequest(segments=["introduction"], depth="quick", cloud=False), ["introduction"], {"tok_s": 5.0, "seconds": 1.0, "model": "stub"})
    assert local["cloud_agents"] == 5      # the estimate describes the team that is configured; a local run configures none:
    llm.runtime.configure(1, cloud=False)
    local = estimate.compute(project, GenerateRequest(segments=["introduction"], depth="quick", cloud=False), ["introduction"], {"tok_s": 5.0, "seconds": 1.0, "model": "stub"})
    assert local["cloud_agents"] == 0 and local["lanes"] == 1 and local["speed_source"] == "probe" and local["remaining"] > est["remaining"]

    history.record(project.id, "run.started", "Fabrication started", model="gemma4:12b", models=["gemma4:12b"], cloud_models=["claude-opus-5-5 (Anthropic)"])
    made = history.ai_statement(project)
    assert made["facts"]["cloud_models"] == ["claude-opus-5-5 (Anthropic)"]
    assert "the gemma4:12b language model on the author's own computer and the claude-opus-5-5 (Anthropic) language model through the provider's online service" in made["statement"]
