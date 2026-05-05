from __future__ import annotations

import base64
import sys
from types import SimpleNamespace

import pytest
from pydantic_ai.exceptions import ModelRetry

from app.core.config import Settings
from app.core.toolkits.email import EmailAttachment, EmailToolkit


def make_ctx(*, workspace_root, settings, session_id: str = "session-1"):
    return SimpleNamespace(
        deps=SimpleNamespace(
            settings=settings,
            workspace_dir=workspace_root / session_id,
            session_id=session_id,
            skill_name=None,
        )
    )


class StubSettings:
    resend_default_from = "noreply@ferryman.app"

    def __init__(self) -> None:
        self.values = {
            "email.resend.api_key": "test-api-key",
            "email.resend.default_from": "noreply@ferryman.app",
        }

    def get_setting(self, key, default=None):
        return self.values.get(key, default)

    def get(self, key, default=None):
        return self.values.get(key, default)


class FakeEmails:
    sent: list[dict] = []

    @staticmethod
    def send(params):
        FakeEmails.sent.append(params)
        return {"id": "email-123"}


class FakeResend:
    api_key = None
    Emails = FakeEmails


@pytest.mark.asyncio
async def test_send_email_supports_multiple_local_and_remote_attachments(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "resend", FakeResend)
    FakeEmails.sent = []
    workspace = tmp_path / "session-1"
    workspace.mkdir()
    (workspace / "report.txt").write_text("hello report", encoding="utf-8")

    result = await EmailToolkit.send_email(
        make_ctx(workspace_root=tmp_path, settings=StubSettings()),
        to=[" support@ferryman.app "],
        subject=" Hello ",
        html="<p>Hi</p>",
        attachments=[
            EmailAttachment(filename="report.txt", path="report.txt"),
            EmailAttachment(filename="invoice.pdf", url="https://example.com/invoice.pdf"),
        ],
    )

    assert FakeResend.api_key == "test-api-key"
    assert result["attachment_count"] == 2
    sent = FakeEmails.sent[0]
    assert sent["from"] == "noreply@ferryman.app"
    assert sent["to"] == ["support@ferryman.app"]
    assert sent["attachments"][0] == {
        "filename": "report.txt",
        "content": base64.b64encode(b"hello report").decode("ascii"),
    }
    assert sent["attachments"][1] == {
        "filename": "invoice.pdf",
        "path": "https://example.com/invoice.pdf",
    }


@pytest.mark.asyncio
async def test_send_email_rejects_missing_api_key(tmp_path):
    settings = StubSettings()
    settings.values["email.resend.api_key"] = ""

    with pytest.raises(ModelRetry, match="Resend API Key is not configured"):
        await EmailToolkit.send_email(
            make_ctx(workspace_root=tmp_path, settings=settings),
            to=["support@ferryman.app"],
            subject="Hello",
            text="Hi",
        )


@pytest.mark.asyncio
async def test_send_email_rejects_escaping_attachment_path(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    with pytest.raises(ModelRetry, match="Invalid attachment path"):
        await EmailToolkit.send_email(
            make_ctx(workspace_root=tmp_path, settings=StubSettings()),
            to=["support@ferryman.app"],
            subject="Hello",
            text="Hi",
            attachments=[EmailAttachment(filename="outside.txt", path="../outside.txt")],
        )


def test_seed_runtime_defaults_writes_email_defaults(session, tmp_path, monkeypatch):
    defaults_path = tmp_path / "runtime_defaults.json"
    defaults_path.write_text(
        """
        {
          "email": {
            "resend": {
              "api_key": "packaged-key",
              "default_from": "noreply@ferryman.app"
            }
          }
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(Settings, "_runtime_defaults_path", staticmethod(lambda: defaults_path))

    settings = Settings()
    settings.seed_runtime_defaults()

    assert Settings.get("email.resend.api_key") == "packaged-key"
    assert Settings.get("email.resend.default_from") == "noreply@ferryman.app"
