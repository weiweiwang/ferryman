from __future__ import annotations

import asyncio
import base64
from typing import Optional

from pydantic import BaseModel, ConfigDict
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.tools import RunContext

from app.core.deps import AgentDeps, get_resend_default_from, get_setting_value
from app.core.toolkits.base import Toolkit
from app.core.toolkits.file import FileToolkit

MAX_EMAIL_BYTES = 40 * 1024 * 1024
EmailParams = dict[str, str | list[str] | list[dict[str, str]]]


class EmailAttachment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str
    path: Optional[str] = None
    url: Optional[str] = None


class EmailToolkit(Toolkit):
    """Send transactional emails through the configured Resend account."""

    @staticmethod
    def get_tools():
        return [EmailToolkit.send_email]

    @staticmethod
    def _require_non_empty(field_name: str, value: str | None) -> str:
        normalized = (value or "").strip()
        if not normalized:
            raise ModelRetry(f"{field_name} must not be empty.")
        return normalized

    @staticmethod
    def _normalize_recipients(field_name: str, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        normalized = [item.strip() for item in values if item and item.strip()]
        if not normalized:
            raise ModelRetry(f"{field_name} must include at least one email address.")
        return normalized

    @staticmethod
    def _resolve_api_key(ctx: RunContext[AgentDeps]) -> str:
        api_key = get_setting_value(ctx.deps, "email.resend.api_key")
        if isinstance(api_key, str) and api_key.strip():
            return api_key.strip()
        raise ModelRetry("Resend API Key is not configured.")

    @staticmethod
    def _resolve_from_email(ctx: RunContext[AgentDeps], from_email: str | None) -> str:
        if from_email and from_email.strip():
            return from_email.strip()
        configured = get_setting_value(ctx.deps, "email.resend.default_from")
        if isinstance(configured, str) and configured.strip():
            return configured.strip()
        return get_resend_default_from(ctx.deps)

    @staticmethod
    def _build_local_attachment(ctx: RunContext[AgentDeps], attachment: EmailAttachment) -> dict[str, str]:
        raw_path = EmailToolkit._require_non_empty("attachment.path", attachment.path)
        try:
            resolved_path = FileToolkit.resolve_read_path(
                ctx.deps,
                ctx.deps.session_id,
                raw_path,
                ctx.deps.skill_name,
            )
        except ValueError:
            raise ModelRetry(f"Invalid attachment path: {raw_path}")

        if not resolved_path.exists() or not resolved_path.is_file():
            raise ModelRetry(f"Attachment file not found: {raw_path}")

        content = resolved_path.read_bytes()
        return {
            "filename": EmailToolkit._require_non_empty("attachment.filename", attachment.filename),
            "content": base64.b64encode(content).decode("ascii"),
        }

    @staticmethod
    def _build_remote_attachment(attachment: EmailAttachment) -> dict[str, str]:
        url = EmailToolkit._require_non_empty("attachment.url", attachment.url)
        if not (url.startswith("https://") or url.startswith("http://")):
            raise ModelRetry("attachment.url must start with http:// or https://.")
        return {
            "filename": EmailToolkit._require_non_empty("attachment.filename", attachment.filename),
            "path": url,
        }

    @staticmethod
    def _build_attachments(
        ctx: RunContext[AgentDeps],
        attachments: list[EmailAttachment] | None,
    ) -> list[dict[str, str]]:
        payload: list[dict[str, str]] = []
        for attachment in attachments or []:
            has_path = bool(attachment.path and attachment.path.strip())
            has_url = bool(attachment.url and attachment.url.strip())
            if has_path == has_url:
                raise ModelRetry("Each attachment must provide exactly one of path or url.")
            payload.append(
                EmailToolkit._build_local_attachment(ctx, attachment)
                if has_path
                else EmailToolkit._build_remote_attachment(attachment)
            )
        return payload

    @staticmethod
    def _estimate_payload_size(params: EmailParams) -> int:
        total = 0
        for key in ("html", "text", "subject"):
            value = params.get(key)
            if isinstance(value, str):
                total += len(value.encode("utf-8"))
        attachments = params.get("attachments")
        if isinstance(attachments, list):
            for attachment in attachments:
                if isinstance(attachment, dict):
                    content = attachment.get("content")
                    if isinstance(content, str):
                        total += len(content.encode("ascii"))
        return total

    @staticmethod
    def _send_with_resend(api_key: str, params: EmailParams) -> object:
        import resend

        resend.api_key = api_key
        return resend.Emails.send(params)

    @staticmethod
    def _normalize_provider_result(result: object) -> object:
        if hasattr(result, "model_dump"):
            result = result.model_dump()
        if result is None or isinstance(result, (str, int, float, bool)):
            return result
        if isinstance(result, dict):
            return {str(key): EmailToolkit._normalize_provider_result(value) for key, value in result.items()}
        if isinstance(result, (list, tuple, set)):
            return [EmailToolkit._normalize_provider_result(value) for value in result]
        return str(result)

    @staticmethod
    async def send_email(
        ctx: RunContext[AgentDeps],
        to: list[str],
        subject: str,
        html: Optional[str] = None,
        text: Optional[str] = None,
        from_email: Optional[str] = None,
        cc: Optional[list[str]] = None,
        bcc: Optional[list[str]] = None,
        reply_to: Optional[list[str]] = None,
        attachments: Optional[list[EmailAttachment]] = None,
    ) -> dict[str, object]:
        """Send an email with optional multiple attachments through Resend.

        Local attachment paths are resolved from the current session workspace
        or the active skill's read-only resources.
        """
        api_key = EmailToolkit._resolve_api_key(ctx)
        normalized_to = EmailToolkit._normalize_recipients("to", to)
        if not normalized_to:
            raise ModelRetry("to must include at least one email address.")

        normalized_subject = EmailToolkit._require_non_empty("subject", subject)
        normalized_html = html.strip() if html and html.strip() else None
        normalized_text = text.strip() if text and text.strip() else None
        if not normalized_html and not normalized_text:
            raise ModelRetry("Either html or text must be provided.")

        params: EmailParams = {
            "from": EmailToolkit._resolve_from_email(ctx, from_email),
            "to": normalized_to,
            "subject": normalized_subject,
        }
        if normalized_html:
            params["html"] = normalized_html
        if normalized_text:
            params["text"] = normalized_text

        for key, values in {
            "cc": cc,
            "bcc": bcc,
            "reply_to": reply_to,
        }.items():
            normalized = EmailToolkit._normalize_recipients(key, values)
            if normalized:
                params[key] = normalized

        attachment_payload = EmailToolkit._build_attachments(ctx, attachments)
        if attachment_payload:
            params["attachments"] = attachment_payload

        estimated_size = EmailToolkit._estimate_payload_size(params)
        if estimated_size > MAX_EMAIL_BYTES:
            raise ModelRetry("Email payload exceeds Resend's 40MB limit.")

        result = await asyncio.to_thread(EmailToolkit._send_with_resend, api_key, params)
        return {
            "provider": "resend",
            "from": params["from"],
            "to": normalized_to,
            "subject": normalized_subject,
            "attachment_count": len(attachment_payload),
            "result": EmailToolkit._normalize_provider_result(result),
        }
