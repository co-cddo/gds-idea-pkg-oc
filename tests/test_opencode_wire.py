"""What OpenCode actually sends to Bedrock for a profile, compared with what it sends for the model directly.

OpenCode and the AI SDK decide how to talk to a Bedrock model from its id, and a profile's id is an ARN that
does not say the model is Claude. Checking what OpenCode *resolves* is not enough: the first version of the
profile config resolved identically to the model and still failed on the wire. So these tests point the real
OpenCode at a local server that records each request (and answers with an error), and compare the requests.

No AWS call is made: credentials are dummies and the endpoint is local. They need the ``opencode`` command,
so they run with ``pytest -m integration``.
"""

import http.server
import json
import os
import pathlib
import pwd
import shutil
import subprocess
import threading
import urllib.parse

import pytest

from idea_oc.opencode_config import apply_plan, plan_config
from idea_oc.profiles import load_profiles

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("opencode") is None, reason="needs the opencode command"),
]

PROFILES = load_profiles()
DIRECT_MODEL = "eu.anthropic.claude-sonnet-5-5"
EFFORTS = PROFILES.model.efforts


class _Recorder(http.server.BaseHTTPRequestHandler):
    requests: list[dict] = []

    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get("content-length", 0)))
        _Recorder.requests.append({"path": self.path, "body": json.loads(body or b"{}")})
        payload = json.dumps({"message": "recorded by the test server"}).encode()
        self.send_response(400)
        self.send_header("content-type", "application/json")
        self.send_header("x-amzn-errortype", "ValidationException")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def endpoint():
    server = http.server.HTTPServer(("127.0.0.1", 0), _Recorder)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture
def capture(tmp_path, endpoint):
    """Return ``capture(profile=..., variant=...)``: the main request OpenCode makes for that setup."""
    counter = iter(range(1000))

    def run(*, profile: bool, variant: str | None = None, with_prompt: bool = True) -> dict:
        home = tmp_path / f"run{next(counter)}"
        config_path = home / "xdg" / "opencode" / "opencode.json"
        config_path.parent.mkdir(parents=True)
        if profile:  # the config idea-oc itself writes, so the real thing is what gets tested
            apply_plan(plan_config(config_path, home / "store", "ds"), config_path)
            config = json.loads(config_path.read_text())
            if not with_prompt:
                config.pop("agent")
            model = PROFILES.model_ref("ds")
        else:
            config, model = {}, f"amazon-bedrock/{DIRECT_MODEL}"
        # idea-oc's config names the bedrockonly AWS profile. Replace the options so the dummy credentials in
        # the environment are used instead, and so nothing can reach a real AWS account.
        config.setdefault("provider", {}).setdefault("amazon-bedrock", {})["options"] = {
            "region": "eu-west-2",
            "endpoint": endpoint,
        }
        config["enabled_providers"] = ["amazon-bedrock"]
        config_path.write_text(json.dumps(config))

        project = home / "project"
        project.mkdir()
        subprocess.run(["git", "init", "-q", "."], cwd=project, check=True)
        env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}
        env.update(
            {f"XDG_{name}_HOME": str(home / "xdg") for name in ("CONFIG", "DATA", "STATE")},
            # The cache holds OpenCode's model catalogue. The test environment fakes $HOME, so ask for the real one.
            XDG_CACHE_HOME=str(pathlib.Path(pwd.getpwuid(os.getuid()).pw_dir) / ".cache"),
            AWS_ACCESS_KEY_ID="AKIDEXAMPLEEXAMPLE",
            AWS_SECRET_ACCESS_KEY="dummysecretdummysecretdummysecret",
            AWS_REGION="eu-west-2",
        )
        _Recorder.requests = []
        command = ["opencode", "run", "--model", model, *(["--variant", variant] if variant else []), "hello"]
        try:
            subprocess.run(command, cwd=project, env=env, capture_output=True, text=True, timeout=90)
        except subprocess.TimeoutExpired:
            pass
        main = [r for r in _Recorder.requests if "haiku" not in r["path"]]  # the other request names the session
        assert main, "OpenCode made no request to the test server"
        return main[0]

    return run


def system_text(request: dict) -> str:
    return "\n".join(block["text"] for block in request["body"]["system"] if "text" in block)


def extra_fields(request: dict) -> dict:
    return request["body"].get("additionalModelRequestFields", {})


def test_requests_go_through_the_profile(capture):
    request = capture(profile=True)

    model_in_url = urllib.parse.unquote(request["path"].split("/model/")[1].split("/converse")[0])
    assert model_in_url == PROFILES.arn("ds")


def test_prompt_caching_is_on_for_a_profile_as_it_is_for_the_model(capture):
    profile, direct = capture(profile=True), capture(profile=False)

    assert json.dumps(profile["body"]).count("cachePoint") == json.dumps(direct["body"]).count("cachePoint") > 0


def test_the_tools_offered_are_the_same(capture):
    profile, direct = capture(profile=True), capture(profile=False)

    assert profile["body"]["toolConfig"] == direct["body"]["toolConfig"]


def test_without_a_variant_no_reasoning_settings_are_sent_either_way(capture):
    profile, direct = capture(profile=True), capture(profile=False)

    assert extra_fields(profile) == extra_fields(direct) == {}
    assert profile["body"]["inferenceConfig"] == direct["body"]["inferenceConfig"]


@pytest.mark.parametrize("effort", EFFORTS)
def test_every_reasoning_level_is_sent_in_the_format_claude_expects(capture, effort):
    """Through a profile OpenCode would send ``reasoningConfig``, which Bedrock rejects for Claude."""
    profile, direct = capture(profile=True, variant=effort), capture(profile=False, variant=effort)

    assert "reasoningConfig" not in extra_fields(profile)
    assert extra_fields(profile) == extra_fields(direct)


def test_the_agents_get_the_claude_instructions_not_the_general_ones(capture):
    profile, direct = capture(profile=True), capture(profile=False)

    differing = {
        line
        for line in set(system_text(profile).splitlines()) ^ set(system_text(direct).splitlines())
        if line.strip() not in ("", "-")
    }
    # the only difference is the line naming the model, which shows the ARN rather than the model
    assert {line.split(" The exact")[0] for line in differing} == {
        f"You are powered by the model named {PROFILES.arn('ds')}.",
        f"You are powered by the model named {DIRECT_MODEL}.",
    }


def test_without_the_prompt_file_a_profile_gets_the_general_instructions(capture):
    """The limit that the prompt file works around. If OpenCode fixes it, this fails and the file can go."""
    request = capture(profile=True, with_prompt=False)

    assert system_text(request).startswith("You are opencode, an interactive CLI tool")
