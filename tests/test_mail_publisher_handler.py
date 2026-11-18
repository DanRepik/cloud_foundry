"""The mail Lambda must not report success for mail it failed to send:
SNS/SQS delete a message once the handler returns normally."""

import importlib
import json
import sys
import types

import pytest


@pytest.fixture
def mail(monkeypatch):
    monkeypatch.setenv("MAIL_ORIGIN", "noreply@example.com")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setitem(sys.modules, "jinja2", types.SimpleNamespace(Template=None))
    sys.modules.pop("cloud_foundry.services.mail_publisher", None)
    module = importlib.import_module("cloud_foundry.services.mail_publisher")
    monkeypatch.setattr(module, "render_template", lambda name, ctx: "<p>hi</p>")
    return module


def _message(subject):
    return json.dumps(
        {
            "template_name": "t.html",
            "context": {},
            "recipients": ["a@b.c"],
            "subject": subject,
        }
    )


def _fail_on(module, monkeypatch, bad_subject):
    def send_email(recipients, subject, body, cc, bcc):
        if subject == bad_subject:
            raise RuntimeError("SES down")
        return {"MessageId": subject}

    monkeypatch.setattr(module, "send_email", send_email)


def test_sqs_reports_only_failed_records(mail, monkeypatch):
    _fail_on(mail, monkeypatch, "bad")
    event = {
        "Records": [
            {"messageId": "m1", "body": _message("ok")},
            {"messageId": "m2", "body": _message("bad")},
            {"messageId": "m3", "body": _message("ok")},
        ]
    }

    assert mail.handler(event, None) == {
        "batchItemFailures": [{"itemIdentifier": "m2"}]
    }


def test_sns_failure_raises_so_lambda_retries(mail, monkeypatch):
    _fail_on(mail, monkeypatch, "bad")
    event = {"Records": [{"Sns": {"Message": _message("bad")}}]}

    with pytest.raises(RuntimeError, match="SES down"):
        mail.handler(event, None)
