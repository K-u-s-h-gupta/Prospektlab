import smtplib
import os
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ==========================================
# Email Configuration (Set these in your .env)
# ==========================================
# For Google Workspace / Gmail: smtp.gmail.com (Port 587)
# For Outlook / Office 365: smtp.office365.com (Port 587)
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER = os.environ.get("SMTP_USER", "your-company-email@example.com")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "your-app-password")
FROM_EMAIL = SMTP_USER
FROM_NAME = "ProspektLab Intelligence"

def send_email_sync(to_email: str, subject: str, html_body: str):
    """Synchronously sends an email using smtplib."""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{FROM_NAME} <{FROM_EMAIL}>"
        msg["To"] = to_email

        # Attach HTML content
        part = MIMEText(html_body, "html")
        msg.attach(part)

        # Connect to SMTP server
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls() # Secure the connection
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(FROM_EMAIL, to_email, msg.as_string())
            
        print(f"Successfully sent email to {to_email}")
        return True
    except Exception as e:
        print(f"Failed to send email to {to_email}: {e}")
        return False

def send_email_async(to_email: str, subject: str, html_body: str):
    """
    Asynchronously sends an email by spinning up a lightweight thread.
    This prevents the FastAPI request from blocking while the email sends.
    """
    thread = threading.Thread(
        target=send_email_sync, 
        args=(to_email, subject, html_body)
    )
    thread.start()


# ==========================================
# Pre-built Email Templates
# ==========================================

def send_verification_email(to_email: str, code: str):
    subject = "Your ProspektLab Verification Code"
    html_body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #333;">
        <h2 style="color: #7da8ff;">ProspektLab</h2>
        <p>Hello,</p>
        <p>Your email verification code is:</p>
        <div style="background-color: #f4f4f4; padding: 15px; border-radius: 8px; text-align: center; margin: 20px 0;">
            <span style="font-size: 24px; font-weight: bold; font-family: monospace; letter-spacing: 5px;">{code}</span>
        </div>
        <p>This code will expire in 10 minutes.</p>
        <p>If you did not request this, please ignore this email.</p>
        <br>
        <p style="font-size: 12px; color: #999;">© 2026 ProspektLab Intelligence</p>
    </div>
    """
    send_email_async(to_email, subject, html_body)

def send_password_reset_email(to_email: str, code: str):
    subject = "Reset Your ProspektLab Password"
    html_body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #333;">
        <h2 style="color: #7da8ff;">ProspektLab Password Reset</h2>
        <p>Hello,</p>
        <p>We received a request to reset your password. Use the code below to complete the reset process:</p>
        <div style="background-color: #f4f4f4; padding: 15px; border-radius: 8px; text-align: center; margin: 20px 0;">
            <span style="font-size: 24px; font-weight: bold; font-family: monospace; letter-spacing: 5px;">{code}</span>
        </div>
        <p>This code will expire in 10 minutes. If you did not request a password reset, you can safely ignore this email.</p>
        <br>
        <p style="font-size: 12px; color: #999;">© 2026 ProspektLab Intelligence</p>
    </div>
    """
    send_email_async(to_email, subject, html_body)
