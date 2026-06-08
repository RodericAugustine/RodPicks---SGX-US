import os, smtplib
from email.mime.text import MIMEText

pw = os.environ.get("HC15_EMAIL_PASS", "")
if not pw:
    print("❌ HC15_EMAIL_PASS env variable not set.")
    print("   Run: [System.Environment]::SetEnvironmentVariable('HC15_EMAIL_PASS','your-app-password','User')")
else:
    try:
        msg = MIMEText("Test from HC15 AutoTrader — email reminder is working!")
        msg["Subject"] = "HC15 Connection Test ✅"
        msg["From"]    = "tayboonhao@gmail.com"
        msg["To"]      = "tayboonhao@gmail.com"
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login("tayboonhao@gmail.com", pw)
            s.sendmail("tayboonhao@gmail.com", "tayboonhao@gmail.com", msg.as_string())
        print("✅ Email sent — check your inbox at tayboonhao@gmail.com")
    except smtplib.SMTPAuthenticationError:
        print("❌ Authentication failed — App Password is wrong or not set up.")
        print("   Go to: https://myaccount.google.com/apppasswords")
    except Exception as e:
        print(f"❌ Error: {e}")
