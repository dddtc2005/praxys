"""Unit tests for the optional SMTP email sender (api/email_sender.py).

Focus: the security-relevant behavior — availability gating, TLS transport
selection, header-injection refusal, and that credentials never surface in
logs — without touching a real SMTP server (smtplib is monkeypatched).
"""
from __future__ import annotations

import logging
import smtplib

import pytest

from api import email_sender as es


class _FakeSMTP:
    """Records calls; stands in for smtplib.SMTP / SMTP_SSL."""

    instances: list["_FakeSMTP"] = []

    def __init__(self, host, port, context=None, timeout=None):
        self.host = host
        self.port = port
        self.context = context
        self.timeout = timeout
        self.logged_in = None
        self.started_tls = False
        self.sent: list = []
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        self.started_tls = True

    def login(self, user, password):
        self.logged_in = (user, password)

    def send_message(self, msg):
        self.sent.append(msg)


@pytest.fixture(autouse=True)
def _reset():
    _FakeSMTP.instances = []
    yield


def _configure(monkeypatch, **over):
    env = {
        "PRAXYS_SMTP_HOST": "smtp.exmail.qq.com",
        "PRAXYS_SMTP_USER": "no-reply@praxys.run",
        "PRAXYS_SMTP_PASSWORD": "s3cr3t-authcode",
        "PRAXYS_SMTP_FROM": "Praxys <no-reply@praxys.run>",
    }
    env.update(over)
    for k in ("PRAXYS_SMTP_HOST", "PRAXYS_SMTP_USER", "PRAXYS_SMTP_PASSWORD",
              "PRAXYS_SMTP_FROM", "PRAXYS_SMTP_PORT", "PRAXYS_SMTP_STARTTLS"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)


def test_not_available_when_unset(monkeypatch):
    for k in ("PRAXYS_SMTP_HOST", "PRAXYS_SMTP_USER", "PRAXYS_SMTP_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    assert es.is_available() is False
    assert es.send_email("a@b.com", "hi", "body") is False


def test_available_when_configured(monkeypatch):
    _configure(monkeypatch)
    assert es.is_available() is True


def test_send_success_uses_ssl_and_logs_in(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _FakeSMTP)
    ok = es.send_email("runner@example.com", "Subject", "text body", "<p>html</p>")
    assert ok is True
    assert len(_FakeSMTP.instances) == 1
    inst = _FakeSMTP.instances[0]
    assert inst.host == "smtp.exmail.qq.com"
    assert inst.port == 465
    assert inst.context is not None  # TLS context passed
    assert inst.logged_in == ("no-reply@praxys.run", "s3cr3t-authcode")
    assert len(inst.sent) == 1
    msg = inst.sent[0]
    assert msg["To"] == "runner@example.com"
    assert msg["Subject"] == "Subject"
    assert msg["From"] == "Praxys <no-reply@praxys.run>"


def test_starttls_path_on_587(monkeypatch):
    _configure(monkeypatch, PRAXYS_SMTP_PORT="587", PRAXYS_SMTP_STARTTLS="true")
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    ok = es.send_email("runner@example.com", "Subject", "body")
    assert ok is True
    inst = _FakeSMTP.instances[0]
    assert inst.port == 587
    assert inst.started_tls is True


def test_rejects_malformed_recipient(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _FakeSMTP)
    assert es.send_email("not-an-email", "Subject", "body") is False
    assert _FakeSMTP.instances == []  # never connected


def test_rejects_header_injection_in_subject(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _FakeSMTP)
    assert es.send_email("a@b.com", "Subj\r\nBcc: evil@x.com", "body") is False
    assert _FakeSMTP.instances == []


def test_rejects_crlf_in_recipient(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _FakeSMTP)
    assert es.send_email("a@b.com\r\nBcc: evil@x.com", "Subject", "body") is False


def test_failure_never_raises_and_does_not_log_password(monkeypatch, caplog):
    _configure(monkeypatch)

    class _Boom(_FakeSMTP):
        def login(self, user, password):
            raise smtplib.SMTPAuthenticationError(535, b"bad s3cr3t-authcode")

    monkeypatch.setattr(smtplib, "SMTP_SSL", _Boom)
    with caplog.at_level(logging.DEBUG):
        ok = es.send_email("a@b.com", "Subject", "body")
    assert ok is False  # never raises
    # The auth code must not appear anywhere in the logs.
    assert "s3cr3t-authcode" not in caplog.text


def test_port_defaults_to_465(monkeypatch):
    _configure(monkeypatch)
    assert es._port() == 465