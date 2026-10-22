"""Tests for tica-doall-automate's email notifications."""

import re
import smtplib

import pytest

from tica.cli import _notify, doall_automate

CONFIG = """
subject_prefix = "[TICA test]"

[smtp]
host = "smtp.example.edu"
port = 587
security = "starttls"
username = "tica"
password_file = "{password}"
sender = "TICA <tica@example.edu>"
reply_to = "ops@example.edu"

[recipients]
operators = ["ops@example.edu", "oncall@example.edu"]
downstream = ["archive@example.org"]
escalation = ["maintainer@example.edu", "ops@example.edu"]
"""


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.delenv("TICA_SMTP_PASSWORD", raising=False)
    (tmp_path / "password").write_text("s3cret\n")
    path = tmp_path / "notify.toml"
    path.write_text(CONFIG.format(password=tmp_path / "password"))
    return path


class FakeSMTP:
    sessions = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.calls = host, port, []
        FakeSMTP.sessions.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def starttls(self):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(("login", user, password))

    def send_message(self, message):
        self.calls.append(("send", message))


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.sessions = []
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    return FakeSMTP.sessions


def test_routes_by_audience_without_repeats(config, smtp):
    notifier = _notify.Notifier.from_config(config)
    assert notifier.addresses(("operators", "escalation")) == [
        "ops@example.edu", "oncall@example.edu", "maintainer@example.edu"]

    assert notifier.send(("operators", "escalation"), "Sector 98 o1a: FAILED", "line one\nline two\n")

    [session] = smtp
    assert (session.host, session.port) == ("smtp.example.edu", 587)
    assert session.calls[:2] == ["starttls", ("login", "tica", "s3cret")]
    message = session.calls[2][1]
    assert message["Subject"] == "[TICA test] Sector 98 o1a: FAILED"
    assert message["From"] == "TICA <tica@example.edu>"
    assert message["To"] == "ops@example.edu, oncall@example.edu, maintainer@example.edu"
    assert message["Reply-To"] == "ops@example.edu"
    assert message.get_content() == "line one\nline two\n"          # line breaks kept


def test_password_from_environment_and_ssl_default_port(tmp_path, monkeypatch, smtp):
    monkeypatch.setenv("TICA_SMTP_PASSWORD", "from-env")
    path = tmp_path / "n.toml"
    path.write_text('[smtp]\nhost = "h"\nsecurity = "ssl"\nusername = "u"\nsender = "s@x.org"\n'
                    '[recipients]\noperators = "ops@x.org"\n')
    notifier = _notify.Notifier.from_config(path)
    assert notifier.smtp["port"] == 465 and notifier.smtp["password"] == "from-env"
    assert notifier.recipients["operators"] == ["ops@x.org"]
    assert notifier.recipients["downstream"] == []


@pytest.mark.parametrize("text, problem", [
    ('[smtp]\nsender = "s@x.org"\n', "host is required"),
    ('[smtp]\nhost = "h"\nsender = "s@x.org"\npassword = "p"\n', "do not put the SMTP password"),
    ('[smtp]\nhost = "h"\nsender = "s@x.org"\nusername = "u"\n', "no password"),
    ('[smtp]\nhost = "h"\nsender = "s@x.org"\nsecurity = "tls"\n', "security must be one of"),
    ('[smtp]\nhost = "h"\nsender = "s@x.org"\nhots = "h"\n', "unknown [smtp] setting(s)"),
    ('[smtp]\nhost = "h"\nsender = "s@x.org"\n[recipients]\nmast = ["a@x.org"]\n', "unknown audience"),
    ('[smtp]\nhost = "h"\nsender = "s@x.org"\n[recipients]\noperators = ["not-an-address"]\n',
     "list of email addresses"),
    ('[smtp\nhost = "h"\n', "not valid TOML"),
])
def test_bad_configs(tmp_path, monkeypatch, text, problem):
    monkeypatch.delenv("TICA_SMTP_PASSWORD", raising=False)
    path = tmp_path / "n.toml"
    path.write_text(text)
    with pytest.raises(_notify.NotifyConfigError, match=re.escape(problem)):
        _notify.Notifier.from_config(path)


def test_missing_config(tmp_path):
    with pytest.raises(_notify.NotifyConfigError, match="cannot read mail config"):
        _notify.Notifier.from_config(tmp_path / "none.toml")


def test_send_failure_is_reported_not_raised(config, monkeypatch, capsys):
    def refuse(*args, **kwargs):
        raise ConnectionRefusedError("connection refused")
    monkeypatch.setattr(smtplib, "SMTP", refuse)
    assert not _notify.Notifier.from_config(config).send(("operators",), "s", "b")
    assert "Could not send mail" in capsys.readouterr().out


def test_printing_and_empty_audience(config, smtp, capsys):
    assert _notify.Notifier.printing().send(("downstream",), "Sector 98 o1a delivery ready", "ready\n")
    assert "Notice for downstream: [TICA] Sector 98 o1a delivery ready" in capsys.readouterr().out

    path = config.parent / "ops-only.toml"
    path.write_text('[smtp]\nhost = "h"\nsender = "s@x.org"\n[recipients]\noperators = ["o@x.org"]\n')
    assert _notify.Notifier.from_config(path).send(("downstream",), "ready", "b")
    assert smtp == [] and "No recipients for downstream" in capsys.readouterr().out


def test_doall_mail_options(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TICA_MAIL_SUCCESS", "old@x.org")
    args = doall_automate.build_parser().parse_args(["--caldir", "c", "--mail", str(tmp_path / "none.toml")])
    with pytest.raises(_notify.NotifyConfigError):
        doall_automate.make_notifier(args)
    assert "TICA_MAIL_SUCCESS is no longer used" in capsys.readouterr().out

    assert doall_automate.main(["--caldir", "c", "--records", str(tmp_path / "r.txt"),
                                "--mail", str(tmp_path / "none.toml")]) == 2
    with pytest.raises(SystemExit):
        doall_automate.build_parser().parse_args(["--mail", "x.toml", "--no-mail"])
