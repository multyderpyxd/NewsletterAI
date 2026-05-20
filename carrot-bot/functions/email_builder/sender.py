"""
email_builder/sender.py

Envía el email HTML via Gmail SMTP.
"""

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text      import MIMEText


def send_email(html_body: str, subject: str, bot_name: str) -> None:
    gmail_user     = os.getenv("GMAIL_USER")
    gmail_password = os.getenv("GMAIL_APP_PASSWORD")
    email_to       = os.getenv("EMAIL_TO")

    if not all([gmail_user, gmail_password, email_to]):
        raise RuntimeError("Faltan variables de entorno: GMAIL_USER, GMAIL_APP_PASSWORD o EMAIL_TO")

    message             = MIMEMultipart("alternative")
    message["From"]     = f"{bot_name} <{gmail_user}>"
    message["To"]       = email_to
    message["Subject"]  = subject

    plain = "Tu resumen musical semanal de CarrotBot está disponible en formato HTML."

    message.attach(MIMEText(plain,     "plain", "utf-8"))
    message.attach(MIMEText(html_body, "html",  "utf-8"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(gmail_user, gmail_password)
        server.send_message(message)

    print(f"  ✅ Email enviado a {email_to}")