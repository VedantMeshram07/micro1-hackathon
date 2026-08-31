"""
Emails a report as an attachment via Gmail SMTP + an app password.
Uses Python's built-in smtplib/email — no new pip dependency.
"""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import os


def send_report_email(to_address: str, subject: str, body: str,
                       attachment_path: str | None,
                       gmail_address: str | None, gmail_app_password: str | None) -> dict:
    if not gmail_address or not gmail_app_password:
        return {"attempted": False, "reason": "Gmail credentials not configured"}

    msg = MIMEMultipart()
    msg["From"] = gmail_address
    msg["To"] = to_address
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    if attachment_path and os.path.exists(attachment_path):
        with open(attachment_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            f"attachment; filename={os.path.basename(attachment_path)}",
        )
        msg.attach(part)

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as server:
            server.starttls()
            server.login(gmail_address, gmail_app_password)
            server.sendmail(gmail_address, to_address, msg.as_string())
        return {"attempted": True, "sent": True}
    except smtplib.SMTPException as e:
        return {"attempted": True, "sent": False, "error": str(e)}