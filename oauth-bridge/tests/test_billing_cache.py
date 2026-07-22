import hashlib
import json

from claude_oauth.bridge import (
    BILLING_HEADER_PREFIX,
    CLAUDE_CLI_VERSION,
    _billing_header_text,
    apply_billing_attribution,
    inject_system_prefix,
    normalize_body_for_anthropic_direct,
    rename_tools_outbound,
)

SYSTEM_IDENTITY = "You are Claude Code, Anthropic's official CLI for Claude."


def _run_pipeline(body):
    raw = json.dumps(body).encode()
    b = inject_system_prefix(body)
    b = normalize_body_for_anthropic_direct(b)
    b = apply_billing_attribution(b, raw)
    return rename_tools_outbound(b)


def _count_cache_control(body):
    return json.dumps(body).count('"cache_control"')


def test_cache_breakpoint_anchored_on_last_system_block():
    body = {
        "model": "claude-opus-4-8",
        "system": [
            {"type": "text", "text": SYSTEM_IDENTITY},
            {
                "type": "text",
                "text": "project context " + "x" * 2000,
                "cache_control": {"type": "ephemeral"},
            },
        ],
        "messages": [{"role": "user", "content": [{"type": "text", "text": "task"}]}],
    }
    out = _run_pipeline(body)
    assert "cache_control" in out["system"][-1]
    assert out["system"][-1]["cache_control"] == {"type": "ephemeral"}
    assert _count_cache_control(out) == 1


def test_relocated_blocks_carry_no_cache_control():
    body = {
        "model": "claude-opus-4-8",
        "system": [
            {"type": "text", "text": SYSTEM_IDENTITY},
            {
                "type": "text",
                "text": "ctx " + "y" * 2000,
                "cache_control": {"type": "ephemeral"},
            },
        ],
        "messages": [{"role": "user", "content": [{"type": "text", "text": "go"}]}],
    }
    out = _run_pipeline(body)
    first_user = next(m for m in out["messages"] if m.get("role") == "user")
    blocks = first_user["content"]
    assert not any(isinstance(b, dict) and "cache_control" in b for b in blocks)


def test_string_user_content_becomes_blocks_without_cache_control():
    body = {
        "model": "claude-opus-4-8",
        "system": [
            {"type": "text", "text": SYSTEM_IDENTITY},
            {
                "type": "text",
                "text": "ctx " + "z" * 2000,
                "cache_control": {"type": "ephemeral"},
            },
        ],
        "messages": [{"role": "user", "content": "plain string prompt"}],
    }
    out = _run_pipeline(body)
    first_user = next(m for m in out["messages"] if m.get("role") == "user")
    assert isinstance(first_user["content"], list)
    assert not any(
        isinstance(b, dict) and "cache_control" in b for b in first_user["content"]
    )
    assert _count_cache_control(out) == 1


def test_billing_header_is_constant_across_growing_bodies():
    turn1 = _billing_header_text(b'{"messages":[{"role":"user","content":"hi"}]}')
    turn2 = _billing_header_text(
        b'{"messages":[{"role":"user","content":"hi"},'
        b'{"role":"assistant","content":"hello"},'
        b'{"role":"user","content":"next"}]}'
    )
    turn3 = _billing_header_text(b"a totally different much longer body " * 100)
    assert turn1 == turn2 == turn3


def test_billing_header_format_valid_for_oauth():
    text = _billing_header_text(b"anything")
    expected_fp = hashlib.sha256(CLAUDE_CLI_VERSION.encode()).hexdigest()[:3]
    assert text == (
        f"{BILLING_HEADER_PREFIX} cc_version={CLAUDE_CLI_VERSION}.{expected_fp}; "
        f"cc_entrypoint=cli; cch=00000;"
    )


def test_billing_fingerprint_does_not_depend_on_body():
    assert _billing_header_text(b"") == _billing_header_text(b"x" * 10000)


def test_apply_billing_attribution_is_deterministic():
    def make_body():
        return {
            "system": [
                {
                    "type": "text",
                    "text": "You are Claude Code, Anthropic's official CLI for Claude.",
                },
                {"type": "text", "text": "bulk harness prompt here"},
            ],
            "messages": [{"role": "user", "content": "solve the task"}],
        }

    raw = b'{"messages":[{"role":"user","content":"solve the task"}]}'
    out1 = apply_billing_attribution(make_body(), raw)
    out2 = apply_billing_attribution(make_body(), raw)
    assert out1 == out2


def test_apply_billing_attribution_puts_billing_block_first():
    body = {
        "system": [
            {
                "type": "text",
                "text": "You are Claude Code, Anthropic's official CLI for Claude.",
            },
        ],
        "messages": [{"role": "user", "content": "hi"}],
    }
    out = apply_billing_attribution(
        body, b'{"messages":[{"role":"user","content":"hi"}]}'
    )
    assert out["system"][0]["text"].startswith(BILLING_HEADER_PREFIX)


def test_apply_billing_attribution_idempotent():
    body = {
        "system": [
            {
                "type": "text",
                "text": "You are Claude Code, Anthropic's official CLI for Claude.",
            },
        ],
        "messages": [{"role": "user", "content": "hi"}],
    }
    raw = b'{"messages":[{"role":"user","content":"hi"}]}'
    once = apply_billing_attribution(body, raw)
    twice = apply_billing_attribution(once, raw)
    assert once == twice
