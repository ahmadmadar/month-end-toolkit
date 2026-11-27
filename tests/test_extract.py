"""Extraction requests and response handling, with a fake Claude client. No API calls, no cost."""

import base64
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from toolkit.config import load_rules
from toolkit.errors import ToolkitError
from toolkit.extract import OUTPUT_SCHEMA, SYSTEM_PROMPT, Extractor
from toolkit.loaders import TicketFile

ROOT = Path(__file__).resolve().parents[1]
NOV = (date(2026, 11, 1), date(2026, 11, 30))
ANSWER = {
    "account_id": "1264", "date": "2026-11-24", "date_raw": "dt 24/11", "site_address": "14 Oak St",
    "extra_bins": 0, "extras_note": None, "contamination": False, "contamination_note": None,
    "serviced": True, "confidence": "high",
}


class FakeClient:
    """Stands in for anthropic.Anthropic: records each request and returns a canned response or raises."""

    def __init__(self, result):
        self.result = result
        self.calls: list[dict] = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def response(answer=ANSWER, stop_reason="end_turn", text=None):
    body = text if text is not None else json.dumps(answer)
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=body)],
        usage=SimpleNamespace(input_tokens=900, output_tokens=120),
    )


def ticket(tmp_path: Path, name: str, data: bytes, kind: str) -> TicketFile:
    path = tmp_path / name
    path.write_bytes(data)
    return TicketFile(name=name, path=path, kind=kind, size_bytes=len(data))


@pytest.fixture
def rules():
    return load_rules(ROOT / "rules" / "rules.yaml")


def run(rules, client, t):
    return Extractor(client, rules, *NOV).extract(t)


def api_error(cls, status):
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("boom", response=httpx2.Response(status, request=req), body=None)


# --- request shape ---

def test_text_request_uses_rules_and_never_sends_file_name(tmp_path, rules):
    client = FakeClient(response())
    t = ticket(tmp_path, "ticket_P202611-0048_copy.txt", b"Acct 1264\ndt 24/11", "text")
    out = run(rules, client, t)
    call = client.calls[0]
    assert call["model"] == rules.model_name
    assert call["max_tokens"] == rules.model_max_tokens
    assert call["thinking"] == {"type": "adaptive"}
    assert call["output_config"]["effort"] == rules.model_effort
    assert call["output_config"]["format"] == {"type": "json_schema", "schema": OUTPUT_SCHEMA}
    assert call["system"] == SYSTEM_PROMPT
    text = call["messages"][0]["content"][0]["text"]
    assert "Run month: 2026-11." in text and "<ticket>\nAcct 1264\ndt 24/11\n</ticket>" in text
    assert "P202611-0048" not in json.dumps(call)
    assert out.record.account_id == "1264" and out.record.source_file == t.name
    assert (out.called_api, out.cacheable, out.failed) == (True, True, False)
    assert (out.input_tokens, out.output_tokens) == (900, 120)


def test_pdf_and_image_requests(tmp_path, rules):
    for name, kind, block_type, media in [
        ("a.pdf", "pdf", "document", "application/pdf"),
        ("b.JPG", "image", "image", "image/jpeg"),
        ("c.png", "image", "image", "image/png"),
    ]:
        client = FakeClient(response())
        run(rules, client, ticket(tmp_path, name, b"\x89fake-bytes", kind))
        block = client.calls[0]["messages"][0]["content"][0]
        assert block["type"] == block_type
        assert block["source"]["media_type"] == media
        assert base64.standard_b64decode(block["source"]["data"]) == b"\x89fake-bytes"


def test_schema_requires_every_field():
    assert set(OUTPUT_SCHEMA["required"]) == set(OUTPUT_SCHEMA["properties"])
    assert OUTPUT_SCHEMA["additionalProperties"] is False


# --- no API call ---

def test_empty_and_oversized_files_skip_the_api(tmp_path, rules):
    client = FakeClient(response())
    empty = run(rules, client, ticket(tmp_path, "e.txt", b"  \n", "text"))
    big = run(rules, client, ticket(tmp_path, "big.txt", b"x" * (1024 * 1024 + 1), "text"))
    assert client.calls == []
    assert empty.record.confidence == "low" and "empty" in empty.record.problems[0]
    assert "too large" in big.record.problems[0]
    assert not empty.called_api and not empty.cacheable


# --- answers ---

@pytest.mark.parametrize(
    "resp, problem",
    [
        (response(stop_reason="refusal"), "declined"),
        (response(stop_reason="max_tokens"), "cut off"),
        (response(text="not json"), "not a set of ticket fields"),
        (response(answer={**ANSWER, "account_id": "12?4"}), "not all digits"),
    ],
)
def test_bad_answers_become_low_confidence_and_are_cached(tmp_path, rules, resp, problem):
    out = run(rules, FakeClient(resp), ticket(tmp_path, "t.txt", b"x", "text"))
    assert out.record.confidence == "low"
    assert any(problem in p for p in out.record.problems)
    assert out.cacheable and not out.failed


# --- API errors ---

@pytest.mark.parametrize(
    "error, note",
    [
        (api_error(anthropic.RateLimitError, 429), "rate limited"),
        (api_error(anthropic.InternalServerError, 500), "API error 500"),
        (api_error(anthropic.BadRequestError, 400), "rejected the request"),
        (anthropic.APIConnectionError(request=httpx2.Request("POST", "https://x")), "could not reach"),
    ],
)
def test_temporary_errors_fail_the_ticket_not_the_run(tmp_path, rules, error, note):
    out = run(rules, FakeClient(error), ticket(tmp_path, "t.txt", b"x", "text"))
    assert out.failed and not out.cacheable
    assert note in out.note
    assert out.record.confidence == "low" and "Run again" in out.record.problems[0]


@pytest.mark.parametrize(
    "error, message",
    [
        (api_error(anthropic.AuthenticationError, 401), "key was rejected"),
        (api_error(anthropic.PermissionDeniedError, 403), "key was rejected"),
        (api_error(anthropic.NotFoundError, 404), "model.name"),
    ],
)
def test_key_and_model_errors_stop_the_run(tmp_path, rules, error, message):
    with pytest.raises(ToolkitError, match=message):
        run(rules, FakeClient(error), ticket(tmp_path, "t.txt", b"x", "text"))
