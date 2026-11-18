import asyncio
import re
from datetime import timedelta
from unittest.mock import MagicMock, Mock

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.crypto import decrypt
from app.core.errors import RateLimited
from app.core.ratelimit import _local, hit
from app.db.base import utcnow
from app.db.session import session_scope
from app.models import AccountToken, MailOutbox, RateCounter, User
from app.services import mail


async def email_token(subject):
    async with session_scope() as s:
        row = (await s.execute(select(MailOutbox).where(MailOutbox.subject == subject)
            .order_by(MailOutbox.created_at.desc()))).scalars().first()
        assert row is not None
        body = decrypt(row.encrypted_body)
        token = re.search(r"#token=([\w-]+)", body).group(1)
        assert token not in row.encrypted_body
        assert not (await s.execute(select(AccountToken).where(AccountToken.token_hash == token))).scalar_one_or_none()
        return token


async def test_reset_revokes_all_sessions_and_is_single_use(client, auth):
    headers, data = auth
    known = await client.post("/auth/forgot-password", json={"email": "OWNER@example.com"})
    unknown = await client.post("/auth/forgot-password", json={"email": "absent@example.com"})
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()
    token = await email_token("Reset your Kruvim password")
    payload = {"token": token, "new_password": "a-new-secure-password"}
    assert (await client.post("/auth/reset-password", json=payload)).status_code == 200
    assert (await client.get("/auth/me", headers=headers)).status_code == 401
    assert (await client.post("/auth/refresh", json={"refresh_token": data["refresh_token"]})).status_code == 401
    assert (await client.post("/auth/reset-password", json=payload)).status_code == 400
    assert (await client.post("/auth/login", json={"email": data["user"]["email"], "password": "correct-horse-battery"})).status_code == 401
    login = await client.post("/auth/login", json={"email": data["user"]["email"], "password": payload["new_password"]})
    assert login.status_code == 200
    assert (await client.get("/auth/me", headers={"Authorization": "Bearer " + login.json()["access_token"]})).status_code == 200


async def test_verify_purpose_expiry_and_replay(client, auth):
    headers, _ = auth
    token = await email_token("Verify your Kruvim email")
    assert (await client.get("/auth/me", headers=headers)).json()["user"]["email_verified"] is False
    assert (await client.post("/auth/reset-password", json={"token": token, "new_password": "another-password"})).status_code == 400
    assert (await client.post("/auth/verify-email", json={"token": token})).status_code == 200
    assert (await client.get("/auth/me", headers=headers)).json()["user"]["email_verified"] is True
    assert (await client.post("/auth/verify-email", json={"token": token})).status_code == 400
    await client.post("/auth/forgot-password", json={"email": "owner@example.com"})
    reset = await email_token("Reset your Kruvim password")
    async with session_scope() as s:
        row = (await s.execute(select(AccountToken).where(AccountToken.purpose == "reset"))).scalar_one()
        row.expires_at = utcnow() - timedelta(seconds=1)
    assert (await client.post("/auth/reset-password", json={"token": reset, "new_password": "another-password"})).status_code == 400


async def test_verification_enforcement_allows_recovery(client, auth):
    headers, _ = auth
    settings.require_email_verification = True
    assert (await client.get("/auth/me", headers=headers)).status_code == 200
    assert (await client.get("/projects", headers=headers)).status_code == 403
    response = await client.post("/auth/verification-email", json={"email": "owner@example.com"})
    assert response.status_code == 200
    token = await email_token("Verify your Kruvim email")
    assert (await client.post("/auth/verify-email", json={"token": token})).status_code == 200
    assert (await client.get("/projects", headers=headers)).status_code == 200


async def test_password_change_revokes_sessions_and_reset_links(client, auth):
    headers, _ = auth
    await client.post("/auth/forgot-password", json={"email": "owner@example.com"})
    token = await email_token("Reset your Kruvim password")
    response = await client.post("/auth/password", headers=headers, json={
        "current_password": "correct-horse-battery", "new_password": "new-account-password"})
    assert response.status_code == 200
    assert (await client.get("/auth/me", headers=headers)).status_code == 401
    assert (await client.post("/auth/reset-password", json={"token": token, "new_password": "another-password"})).status_code == 400


async def test_reissue_invalidates_previous_and_disabled_accounts(client, auth):
    await client.post("/auth/forgot-password", json={"email": "owner@example.com"})
    old = await email_token("Reset your Kruvim password")
    await client.post("/auth/forgot-password", json={"email": "owner@example.com"})
    new = await email_token("Reset your Kruvim password")
    assert new != old
    assert (await client.post("/auth/reset-password", json={"token": old, "new_password": "another-password"})).status_code == 400
    async with session_scope() as s:
        user = (await s.execute(select(User))).scalar_one()
        user.is_active = False
    assert (await client.post("/auth/reset-password", json={"token": new, "new_password": "another-password"})).status_code == 400


async def test_request_throttling_ignores_spoofed_forwarded_ip(client):
    settings.rate_limit_auth_per_minute = 2
    for i in range(2):
        response = await client.post("/auth/forgot-password", json={"email": f"missing{i}@example.com"}, headers={"X-Forwarded-For": f"192.0.2.{i}"})
        assert response.status_code == 200
    response = await client.post("/auth/forgot-password", json={"email": "missing3@example.com"}, headers={"X-Forwarded-For": "192.0.2.3"})
    assert response.status_code == 429


async def test_shared_database_counts_survive_local_reset():
    settings.rate_limit_backend = "database"
    await hit("shared-account", 2)
    _local.clear()
    await hit("shared-account", 2)
    with pytest.raises(RateLimited):
        await hit("shared-account", 2)
    async with session_scope() as s:
        row = (await s.execute(select(RateCounter))).scalar_one()
        assert row.count == 3
        assert "shared-account" not in row.key


async def test_shared_database_concurrent_increments():
    settings.rate_limit_backend = "database"
    results = await asyncio.gather(*(hit("concurrent", 5) for _ in range(12)), return_exceptions=True)
    assert sum(result is None for result in results) == 5
    assert sum(isinstance(result, RateLimited) for result in results) == 7


async def test_production_auto_uses_shared_database_without_redis():
    settings.env = "production"
    await hit("production", 1)
    _local.clear()
    with pytest.raises(RateLimited):
        await hit("production", 1)


async def test_concurrent_reset_consumes_token_once(client, auth):
    await client.post("/auth/forgot-password", json={"email": "owner@example.com"})
    token = await email_token("Reset your Kruvim password")
    responses = await asyncio.gather(*(client.post("/auth/reset-password", json={
        "token": token, "new_password": "a-new-secure-password"}) for _ in range(2)))
    assert sorted(response.status_code for response in responses) == [200, 400]


async def test_outbox_failure_retries_then_delivers(monkeypatch):
    settings.mail_backend = "smtp"
    sender = Mock(side_effect=RuntimeError("sensitive SMTP error"))
    monkeypatch.setattr(mail, "_send", sender)
    async with session_scope() as s:
        mail.enqueue(s, "person@example.com", "Test", "private message")
    await mail.dispatch_pending()
    async with session_scope() as s:
        row = (await s.execute(select(MailOutbox))).scalar_one()
        assert row.delivered_at is None and row.attempts == 1
        assert row.next_attempt_at > utcnow()
        row.next_attempt_at = utcnow() - timedelta(seconds=1)
    sender.side_effect = None
    sender.return_value = True
    await mail.dispatch_pending()
    async with session_scope() as s:
        row = (await s.execute(select(MailOutbox))).scalar_one()
        assert row.delivered_at and row.attempts == 2 and row.encrypted_body == ""


async def test_smtp_uses_tls_and_credentials(monkeypatch):
    settings.mail_backend = "smtp"
    settings.mail_from = "Kruvim <hello@example.com>"
    settings.smtp_host, settings.smtp_username, settings.smtp_password = "smtp.example.com", "account", "secret"
    connection = MagicMock()
    smtp = connection.__enter__.return_value
    smtp.send_message.return_value = {}
    constructor = Mock(return_value=connection)
    monkeypatch.setattr(mail.smtplib, "SMTP", constructor)
    assert mail._send("recipient@example.com", "Subject", "Body")
    smtp.starttls.assert_called_once()
    smtp.login.assert_called_once_with("account", "secret")
    message = smtp.send_message.call_args.args[0]
    assert message["To"] == "recipient@example.com"


@pytest.mark.parametrize("forwarded,expected", [("192.0.2.10", "192.0.2.10"), ("2001:db8::1", "2001:db8::1"), ("bad-ip", "127.0.0.1"), ("192.0.2.10, 192.0.2.11", "127.0.0.1")])
async def test_hosted_ip_uses_only_valid_platform_header(forwarded, expected):
    from starlette.requests import Request

    from app.api.deps import client_ip
    settings.serverless = True
    request = Request({"type": "http", "client": ("127.0.0.1", 1234), "headers": [
        (b"x-forwarded-for", b"192.0.2.99"), (b"x-vercel-forwarded-for", forwarded.encode())]})
    assert client_ip(request) == expected
    settings.serverless = False
    assert client_ip(request) == "127.0.0.1"


async def test_real_smtp_roundtrip_delivers_verification_and_reset(client, auth):
    # Exercise smtplib over a real socket, with a local capture server and no external delivery.
    import socketserver
    import threading
    from email import policy
    from email.parser import BytesParser

    messages = []

    class SMTPHandler(socketserver.StreamRequestHandler):
        def handle(self):
            self.wfile.write(b"220 capture ESMTP ready\r\n")
            while line := self.rfile.readline():
                command = line.decode().strip().upper()
                if command.startswith(("EHLO", "HELO", "MAIL", "RCPT", "RSET")):
                    self.wfile.write(b"250 OK\r\n")
                elif command == "DATA":
                    self.wfile.write(b"354 End with dot\r\n")
                    content = []
                    while chunk := self.rfile.readline():
                        if chunk == b".\r\n":
                            break
                        content.append(chunk[1:] if chunk.startswith(b"..") else chunk)
                    messages.append(BytesParser(policy=policy.default).parsebytes(b"".join(content)))
                    self.wfile.write(b"250 Accepted\r\n")
                elif command == "QUIT":
                    self.wfile.write(b"221 Bye\r\n")
                    return
                else:
                    self.wfile.write(b"502 Unsupported\r\n")

    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), SMTPHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    settings.mail_backend = "smtp"
    settings.smtp_host, settings.smtp_port = server.server_address
    settings.smtp_security, settings.smtp_username = "plain", ""
    settings.mail_from = "accounts@example.com"
    try:
        response = await client.post("/auth/forgot-password", json={"email": "owner@example.com"})
        assert response.status_code == 200
        assert len(messages) == 2
        by_subject = {str(message["Subject"]): message for message in messages}
        for subject, endpoint in [("Verify your Kruvim email", "/auth/verify-email"), ("Reset your Kruvim password", "/auth/reset-password")]:
            message = by_subject[subject]
            assert str(message["To"]) == "owner@example.com"
            token = re.search(r"#token=([\w-]+)", message.get_content()).group(1)
            payload = {"token": token}
            if endpoint.endswith("reset-password"):
                payload["new_password"] = "smtp-tested-password"
            assert (await client.post(endpoint, json=payload)).status_code == 200
            assert (await client.post(endpoint, json=payload)).status_code == 400
        async with session_scope() as s:
            rows = (await s.execute(select(MailOutbox))).scalars().all()
            assert all(row.delivered_at and not row.encrypted_body for row in rows)
    finally:
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        thread.join(timeout=2)
