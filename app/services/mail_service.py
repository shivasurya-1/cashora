from fastapi_mail import FastMail, MessageSchema, ConnectionConfig, MessageType
from app.core.config import settings

conf = ConnectionConfig(
    MAIL_USERNAME=settings.SMTP_USERNAME,
    MAIL_PASSWORD=settings.SMTP_PASSWORD,
    MAIL_FROM=settings.SMTP_FROM,
    MAIL_PORT=settings.SMTP_PORT,
    MAIL_SERVER=settings.SMTP_SERVER,
    MAIL_STARTTLS=True,  # Modern flag for port 587
    MAIL_SSL_TLS=False,  # Modern flag for port 587
    USE_CREDENTIALS=True,
    VALIDATE_CERTS=True
)

async def send_welcome_email(email: str, org_code: str, temp_password: str, name: str):
    html = f"""
    <h3>Welcome to Expense Manager, {name}!</h3>
    <p>Your organization has been successfully set up.</p>
    <p><strong>Organization Code:</strong> {org_code}</p>
    <p><strong>Temporary Password:</strong> {temp_password}</p>
    <p><i>Note: Please change your password immediately after your first login.</i></p>
    <br>
    <p>Best Regards,<br>Fintech Team</p>
    """

    message = MessageSchema(
        subject="Organization Setup Successful",
        recipients=[email],
        body=html,
        subtype=MessageType.html
    )

    try:
        fm = FastMail(conf)
        await fm.send_message(message)
        print(f"✅ Email successfully sent to {email}")
    except Exception as e:
        # This prevents the 500 error from reaching the user
        print(f"❌ Failed to send email to {email}. Error: {str(e)}")

# app/services/mail_service.py

async def send_otp_email(email: str, otp: str):
    html = f"""
    <h3>Password Reset Request</h3>
    <p>You requested an OTP to reset your password.</p>
    <p style="font-size: 24px; font-weight: bold; color: #2c3e50;">{otp}</p>
    <p>This OTP is valid for 5 minutes. If you did not request this, please ignore this email.</p>
    <br>
    <p>Best Regards,<br>Fintech Team</p>
    """

    message = MessageSchema(
        subject="Your Password Reset OTP",
        recipients=[email],
        body=html,
        subtype=MessageType.html
    )

    try:
        fm = FastMail(conf)
        await fm.send_message(message)
        print(f"✅ OTP Email sent to {email}")
    except Exception as e:
        print(f"❌ Failed to send OTP email: {str(e)}")