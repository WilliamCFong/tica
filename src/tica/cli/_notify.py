"""Email notifications for tica-doall-automate.

Recipients and the mail server come from a TOML file (tica-doall-automate
--mail FILE); no addresses are built into TICA. For example:

    [smtp]
    host = "outgoing.example.edu"
    port = 587                    # default: 25, or 465 with security = "ssl"
    security = "starttls"         # "none" (default), "starttls" or "ssl"
    username = "tica"             # optional; then a password is needed:
    password_file = "~/.tica-smtp-password"   # or $TICA_SMTP_PASSWORD
    sender = "TICA pipeline <tica@example.edu>"
    reply_to = "operators@example.edu"        # optional

    [recipients]
    operators = ["operators@example.edu"]     # every event, with details
    downstream = ["archive@example.org"]      # only "delivery ready"
    escalation = ["maintainer@example.edu"]   # errors only

    subject_prefix = "[TICA]"     # optional, at the top level; this is the default

Any audience may be left out or empty. See docs/notify.example.toml.
"""

import os
import smtplib
import tomllib
from email.message import EmailMessage

AUDIENCES = ('operators', 'downstream', 'escalation')
SECURITY = ('none', 'starttls', 'ssl')
DEFAULT_PREFIX = '[TICA]'


class NotifyConfigError(ValueError):
    """The notification config file is missing or invalid."""


def _addresses(value, where):
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(a, str) and '@' in a for a in value):
        raise NotifyConfigError('{} must be a list of email addresses'.format(where))
    return value


class Notifier:
    """Sends a notice to one or more audiences; without SMTP settings, prints it."""

    def __init__(self, recipients=None, smtp=None, prefix=DEFAULT_PREFIX, source=None):
        self.recipients = {a: list((recipients or {}).get(a, [])) for a in AUDIENCES}
        self.smtp = smtp
        self.prefix = prefix
        self.source = source

    @classmethod
    def from_config(cls, path):
        try:
            with open(os.path.expanduser(path), 'rb') as f:
                config = tomllib.load(f)
        except OSError as e:
            raise NotifyConfigError('cannot read mail config {}: {}'.format(path, e.strerror)) from e
        except tomllib.TOMLDecodeError as e:
            raise NotifyConfigError('mail config {} is not valid TOML: {}'.format(path, e)) from e

        unknown = set(config) - {'smtp', 'recipients', 'subject_prefix'}
        if unknown:
            raise NotifyConfigError('unknown setting(s) in {}: {}'.format(path, ', '.join(sorted(unknown))))
        recipients = config.get('recipients', {})
        unknown = set(recipients) - set(AUDIENCES)
        if unknown:
            raise NotifyConfigError('unknown audience(s) in {}: {} (use {})'.format(
                path, ', '.join(sorted(unknown)), ', '.join(AUDIENCES)))
        recipients = {a: _addresses(v, '[recipients] {}'.format(a)) for a, v in recipients.items()}

        smtp = dict(config.get('smtp', {}))
        if 'password' in smtp:
            raise NotifyConfigError('do not put the SMTP password in {}; use [smtp] password_file '
                                    'or $TICA_SMTP_PASSWORD'.format(path))
        unknown = set(smtp) - {'host', 'port', 'security', 'username', 'password_file', 'sender', 'reply_to'}
        if unknown:
            raise NotifyConfigError('unknown [smtp] setting(s) in {}: {}'.format(path, ', '.join(sorted(unknown))))
        for key in ('host', 'sender'):
            if not smtp.get(key):
                raise NotifyConfigError('[smtp] {} is required in {}'.format(key, path))
        smtp.setdefault('security', 'none')
        if smtp['security'] not in SECURITY:
            raise NotifyConfigError('[smtp] security must be one of {}'.format(', '.join(SECURITY)))
        smtp.setdefault('port', 465 if smtp['security'] == 'ssl' else 25)
        if smtp.get('username'):
            smtp['password'] = _password(smtp, path)
        if 'reply_to' in smtp:
            _addresses(smtp['reply_to'], '[smtp] reply_to')
        return cls(recipients, smtp, config.get('subject_prefix', DEFAULT_PREFIX), source=path)

    @classmethod
    def printing(cls):
        """Prints notices instead of sending them (--no-mail, or no --mail config)."""
        return cls()

    def addresses(self, audiences):
        """The recipients of audiences, in order, without repeats."""
        out = []
        for audience in audiences:
            out += [a for a in self.recipients[audience] if a not in out]
        return out

    def send(self, audiences, subject, body):
        """Send a notice; return True if it was sent (or printed), False if sending failed."""
        to = self.addresses(audiences)
        subject = '{} {}'.format(self.prefix, subject) if self.prefix else subject
        if self.smtp is None:
            print('Notice for {}: {}\n{}'.format('/'.join(audiences), subject, body.rstrip()), flush=True)
            return True
        if not to:
            print('No recipients for {}; not mailing "{}"'.format('/'.join(audiences), subject), flush=True)
            return True
        message = EmailMessage()
        message['Subject'] = subject
        message['From'] = self.smtp['sender']
        message['To'] = ', '.join(to)
        if self.smtp.get('reply_to'):
            message['Reply-To'] = ', '.join(_addresses(self.smtp['reply_to'], 'reply_to'))
        message.set_content(body)
        try:
            server_class = smtplib.SMTP_SSL if self.smtp['security'] == 'ssl' else smtplib.SMTP
            with server_class(self.smtp['host'], self.smtp['port'], timeout=60) as server:
                if self.smtp['security'] == 'starttls':
                    server.starttls()
                if self.smtp.get('username'):
                    server.login(self.smtp['username'], self.smtp['password'])
                server.send_message(message)
        except (OSError, smtplib.SMTPException) as e:
            print('Could not send mail "{}" to {} through {}:{}: {}'.format(
                subject, ', '.join(to), self.smtp['host'], self.smtp['port'], e), flush=True)
            return False
        return True


def _password(smtp, path):
    if os.environ.get('TICA_SMTP_PASSWORD'):
        return os.environ['TICA_SMTP_PASSWORD']
    if smtp.get('password_file'):
        try:
            with open(os.path.expanduser(smtp['password_file'])) as f:
                return f.read().strip()
        except OSError as e:
            raise NotifyConfigError('cannot read [smtp] password_file {}: {}'.format(
                smtp['password_file'], e.strerror)) from e
    raise NotifyConfigError('[smtp] username is set in {} but there is no password: set password_file '
                            'or $TICA_SMTP_PASSWORD'.format(path))
