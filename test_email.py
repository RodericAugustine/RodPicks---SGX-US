import os, smtplib
from email.mime.text import MIMEText

pw = os.environ.get("RodPicks_EMAIL_PASS", "")
if not pw:
    print("❌ RodPicks_EMAIL_PASS env variable not set.")
    print("   Run: [System.Environment]::SetEnvironmentVariable('RodPicks_EMAIL_PASS','your-app-password','User')")
else:
    try:
        msg = MIMEText("Test from RodPicks AutoTrader — email reminder is working!")
        msg["Subject"] = "RodPicks Connection Test ✅"
        msg["From"]    = "YOUR_EMAIL@gmail.com"
        msg["To"]      = "YOUR_EMAIL@gmail.com"
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login("YOUR_EMAIL@gmail.com", pw)
            s.sendmail("YOUR_EMAIL@gmail.com", "YOUR_EMAIL@gmail.com", msg.as_string())
        print("✅ Email sent — check your inbox at YOUR_EMAIL@gmail.com")
    except smtplib.SMTPAuthenticationError:
        print("❌ Authentication failed — App Password is wrong or not set up.")
        print("   Go to: https://myaccount.google.com/apppasswords")
    except Exception as e:
        print(f"❌ Error: {e}")
