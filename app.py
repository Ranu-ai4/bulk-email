#!/usr/bin/env python3
"""
Bulk Email Sender - Web UI
"""

import os
import csv
import base64
import re
import time
from pymongo import MongoClient

from pathlib import Path
from threading import Thread
import random
import string
import datetime

import datetime
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import Flask, render_template, request, jsonify, session, redirect
from dotenv import load_dotenv
import requests
import json

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key-123")

app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['UPLOAD_FOLDER'] = 'uploads'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

DB_URI = os.getenv("MONGO_URI", "mongodb://mongo:27017/")
client = MongoClient(DB_URI)
db = client.bulk_emailer
# -----------------------------
# GLOBAL SEND STATE
# -----------------------------

send_state = {
    'is_sending': False,
    'total': 0,
    'sent': 0,
    'failed': 0,
    'errors': [],
    'complete': False
}

# -----------------------------
# SYSTEM EMAIL HELPER
# -----------------------------

def send_system_email(to_email, subject, body_html):
    smtp_host = os.getenv('SMTP_HOST')
    smtp_port = int(os.getenv('SMTP_PORT', 587))
    smtp_user = os.getenv('SMTP_USER')
    smtp_pass = os.getenv('SMTP_PASS')
    if smtp_pass:
        smtp_pass = smtp_pass.replace(' ', '')
    from_email = os.getenv('FROM_EMAIL')
    from_name = os.getenv('FROM_NAME', 'System')

    if not all([smtp_host, smtp_user, smtp_pass]):
        print("SMTP Credentials missing. Cannot send system email.")
        return False

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"{from_name} <{from_email}>"
        msg['To'] = to_email

        html_part = MIMEText(body_html, 'html')
        msg.attach(html_part)

        server = smtplib.SMTP(str(smtp_host), smtp_port)
        server.starttls()
        server.login(str(smtp_user), str(smtp_pass))
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"Error sending system email: {e}")
        return False

# -----------------------------
# LOGIN ROUTES
# -----------------------------

@app.route("/")
def login():
    role = session.get('role')
    if role == 'admin':
        return redirect("/admin-dashboard")
    elif role == 'employee':
        return redirect("/dashboard")
    return render_template("login.html")


@app.route("/admin-dashboard")
def admin_dashboard():
    if session.get('role') != 'admin':
        return redirect("/dashboard")
    return index("index.html")


@app.route("/dashboard")
def employee_dashboard():
    if session.get('role') == 'admin':
        return redirect("/admin-dashboard")
    if not session.get('role'):
        return redirect("/")
    return index("employee.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


@app.route("/send-otp", methods=["POST"])
def send_otp():
    email = request.json.get("email")
    if not email or not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        return jsonify({"success": False, "error": "Valid email required"}), 400

    # ✅ Only authorized users can receive OTP
    user = db.users.find_one({"email": email})
    
    if not user:
        return jsonify({"success": False, "authorized": False, "error": "You are not authorized to access this system."})
        
    if user.get("role") != "admin" and user.get("approved") != 1:
        return jsonify({"success": False, "authorized": False, "error": "You are not authorized to access this system."})

    # Generate 6 digit OTP
    otp = ''.join(random.choices(string.digits, k=6))
    
    # Expire in 10 minutes
    expires_at = datetime.datetime.now() + datetime.timedelta(minutes=10)
    db.otps.update_one(
        {"email": email},
        {"$set": {"otp": otp, "expires_at": expires_at.strftime('%Y-%m-%d %H:%M:%S')}},
        upsert=True
    )
    
    # Send email
    subject = "Your Login Code"
    html = f"<div style='font-family: Arial; padding: 20px;'><h2>Your Login Code</h2><p>Here is your 6-digit verification code to login to the Bulk Email Sender:</p><h1 style='color: #00ff88; letter-spacing: 5px; background: #111; padding: 10px; display: inline-block;'>{otp}</h1><p>This code will expire in 10 minutes.</p></div>"
    success = send_system_email(email, subject, html)
    
    if not success:
        return jsonify({"success": False, "error": "SMTP server failed to send email. Check credentials."})
    
    return jsonify({"success": True})

@app.route("/users")
def get_users():
    if session.get('role') != 'admin':
        return jsonify({"error": "Admin access required"}), 403
    
    users = list(db.users.find({}, {"_id": 0}))
    return jsonify(users)


@app.route("/create-user", methods=["POST"])
def create_user():
    if session.get('role') != 'admin':
        return jsonify({"error": "Admin access required"}), 403
    
    data = request.json
    email = data.get("email")
    approved = data.get("approved", 0)
    
    if not email:
        return jsonify({"success": False, "error": "Email is required"}), 400
        
    db.users.update_one(
        {"email": email},
        {"$set": {"approved": int(approved)}},
        upsert=True
    )
    return jsonify({"success": True, "message": "User created/updated successfully"})


@app.route("/update-user", methods=["POST"])
def update_user():
    if session.get('role') != 'admin':
        return jsonify({"error": "Admin access required"}), 403
    
    data = request.json
    email = data.get("email")
    approved = data.get("approved")
    
    if not email or approved is None:
        return jsonify({"success": False, "error": "Email and approved status are required"}), 400
        
    db.users.update_one(
        {"email": email},
        {"$set": {"approved": int(approved)}}
    )
    return jsonify({"success": True, "message": "User updated successfully"})


@app.route("/delete-user", methods=["POST"])
def delete_user_route():
    if session.get('role') != 'admin':
        return jsonify({"error": "Admin access required"}), 403
    
    data = request.json
    email = data.get("email")
    
    if not email:
        return jsonify({"success": False, "error": "Email is required"}), 400
        
    db.users.delete_one({"email": email})
    return jsonify({"success": True, "message": "User deleted successfully"})


@app.route("/enhance-template", methods=["POST"])
def enhance_template():
    if not session.get('role'):
        return jsonify({"error": "Logging required"}), 403
    
    data = request.json
    html_content = data.get("html")
    user_prompt = data.get("prompt", "").strip()
    
    if not html_content:
        return jsonify({"success": False, "error": "HTML content is required"}), 400
    
    api_key = os.getenv("AI_API_KEY", "").strip()
    print(f"DEBUG: AI_API_KEY present: {bool(api_key)}")
    if api_key:
        print(f"DEBUG: API Key starts with: {api_key[:8]}...")

    if not api_key:
        return jsonify({"success": False, "error": "AI API key not configured"}), 500
        
    # Using configured BaseURL from .env
    base_url = os.getenv("BaseURL", "https://api.groq.com/openai/v1").strip()
    url = f"{base_url}/chat/completions"
    model = "openai/gpt-oss-120b"
    
    # Dynamic System Instructions based on whether there's a specific prompt
    if user_prompt:
        system_instructions = (
            "You are an expert professional email template designer.\n\n"
            "Analyze the following user prompt carefully to automatically detect which mode to use:\n"
            f"\"{user_prompt}\"\n\n"
            "Mode 1 — Generate New Template:\n"
            "If the user's input describes content, topic, features, or an email purpose (e.g. 'holiday greetings', 'product launch', 'monthly newsletter'), generate a COMPLETE, FULL-LENGTH, HIGHLY PROFESSIONAL HTML email template with inline CSS only. Requirements:\n"
            "- Expand the user's short input into full professional email content with proper sentences and paragraphs\n"
            "- Beautiful gradient header with title\n"
            "- Multiple content sections with proper headings and paragraphs\n"
            "- Styled bullet points if needed\n"
            "- Elegant CTA button (dark or brand color, never plain red)\n"
            "- Professional footer with {{name}}, {{company}}, {{year}}, {{support_email}} placeholders\n"
            "- Clean modern design, proper padding and spacing\n"
            "- Minimum 500 words of HTML content\n"
            "- NO external images — use CSS colored blocks only\n"
            "- Should look exactly like a real company newsletter\n\n"
            "Mode 2 — Edit Existing Template:\n"
            "If the user's input is a specific edit instruction (e.g. 'make header blue', 'change font size', 'remove footer'), apply ONLY that specific change to the existing HTML and return the full updated HTML.\n\n"
            "CRITICAL: Return ONLY the raw HTML code. Do not include markdown formating, do not wrap in ```html, and do not add explanatory text."
        )
    else:
        system_instructions = (
            "You are a professional email template designer and copywriter. Enhance the provided HTML email template "
            "to be more professional, engaging, and clear. \n"
            "Rules:\n"
            "1. Maintain all HTML tags and structure exactly as they are.\n"
            "2. Only improve the text content between the tags.\n"
            "3. Keep placeholders like {{group}}, {{name}}, {{greeting}}, etc. unchanged.\n"
            "4. Do not add any new tags or remove existing ones.\n"
            "5. Return ONLY the enhanced HTML code without any markdown formatting or code blocks."
        )
    
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": system_instructions
            },
            {
                "role": "user",
                "content": f"HTML Template:\n{html_content}"
            }
        ]
    }
    
    try:
        print(f"DEBUG: Sending request to {url} with model {model}...")
        response = requests.post(
            url, 
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }, 
            data=json.dumps(payload),
            timeout=120
        )
        response_data = response.json()
        print(f"DEBUG: AI API Response Status: {response.status_code}")
        # print(f"DEBUG: AI API Full Response: {json.dumps(response_data, indent=2)}")
        
        if "choices" in response_data and response_data["choices"]:
            enhanced_html = response_data["choices"][0]["message"]["content"]
            # Basic cleanup in case AI still includes markdown blocks
            enhanced_html = enhanced_html.replace("```html", "").replace("```", "").strip()
            return jsonify({"success": True, "enhanced_html": enhanced_html})
        
        error_info = response_data.get("error", {})
        if isinstance(error_info, str):
            error_msg = error_info
        else:
            error_msg = error_info.get("message", "AI failed to generate content")
            
        print(f"DEBUG: AI Error handled: {error_msg}")
        return jsonify({"success": False, "error": error_msg, "raw": response_data}), 500
            
    except Exception as e:
        print(f"DEBUG: Exception in enhance_template: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/verify-otp", methods=["POST"])
def verify_otp():
    email = request.json.get("email")
    otp = request.json.get("otp")
    
    # Check OTP
    record = db.otps.find_one({"email": email})
    if not record:
        return jsonify({"valid": False, "error": "No OTP requested"})
        
    stored_otp = record.get("otp")
    expires_str = record.get("expires_at")
    expires_at = datetime.datetime.strptime(expires_str, '%Y-%m-%d %H:%M:%S')
    
    if datetime.datetime.now() > expires_at:
        return jsonify({"valid": False, "error": "OTP Expired"})
        
    if str(stored_otp) != str(otp):
        return jsonify({"valid": False, "error": "Invalid OTP"})
            
    # Valid OTP, check user approval status
    user = db.users.find_one({"email": email})
    
    if user:
        if user.get("role") == "admin":
            session['role'] = 'admin'
            session['email'] = email.lower()
            return jsonify({"valid": True, "access_approved": True, "redirect": "/admin-dashboard"})
        elif user.get("approved") == 1:
            session['role'] = 'employee'
            session['email'] = email.lower()
            return jsonify({"valid": True, "access_approved": True, "redirect": "/dashboard"})
            
    return jsonify({"valid": True, "access_approved": False})

@app.route("/check-user", methods=["POST"])
def check_user():

    email = request.json["email"]

    user = db.users.find_one({"email": email})

    if user and user.get("approved") == 1:
        return jsonify({"access": True})

    return jsonify({"access": False})


@app.route("/request-access", methods=["POST"])
def request_access():

    email = request.json["email"]

    if not db.users.find_one({"email": email}):
        db.users.insert_one({"email": email, "approved": 0})
    
    admins = db.users.find({"role": "admin"})
    
    # Notify all Admins
    for adm in admins:
        admin_email = adm.get("email")
        if admin_email:
            send_system_email(
                admin_email,
                "New Access Request: Bulk Emailer",
                f"<p>User <b>{email}</b> has requested employee access to the system. Please login to the dashboard and approve them if authorized.</p>"
            )
    
    # Notify Employee
    send_system_email(
        email,
        "Access Request Received",
        "<p>Your access request has been sent to the Admin. You will receive an email once it is approved.</p>"
    )

    return jsonify({"status": "requested"})


@app.route("/pending")
def pending():

    users = db.users.find({"approved": 0})

    return jsonify([u.get("email") for u in users])


@app.route("/approve", methods=["POST"])
def approve():

    email = request.json["email"]

    db.users.update_one({"email": email}, {"$set": {"approved": 1}})
    
    # Notify Employee they are approved
    send_system_email(
        email,
        "Access Approved: Bulk Emailer",
        "<p>Your access request has been approved by the Admin. You can now login using OTP.</p>"
    )

    return jsonify({"status": "approved"})


# -----------------------------
# EMAIL SYSTEM
# -----------------------------

def validate_email(email: str) -> bool:
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None


def load_csv(file_path: str):
    recipients = []
    invalid_emails = []

    with open(file_path, 'r', encoding='utf-8') as f:

        reader = csv.DictReader(f)

        if 'email' not in reader.fieldnames:
            raise ValueError("CSV must have 'email' column")

        for row_num, row in enumerate(reader, start=2):

            email = row.get('email', '').strip()
            name = row.get('name', '').strip()

            if not email:
                continue

            if validate_email(email):
                recipients.append({
                    'email': email,
                    'name': name
                })
            else:
                invalid_emails.append({
                    'row': row_num,
                    'email': email
                })

    return recipients, invalid_emails


def load_html_template(template_path: str):
    with open(template_path, 'r', encoding='utf-8') as f:
        return f.read()


def personalize_html(html: str, name: str):

    greeting = f"Hi {name}," if name else "Hi,"

    html = html.replace('{{greeting}}', greeting)
    html = html.replace('{{name}}', name)

    return html


def get_config():

    smtp_pass = os.getenv('SMTP_PASS')
    if smtp_pass:
        smtp_pass = smtp_pass.replace(' ', '')

    return {
        'smtp_host': os.getenv('SMTP_HOST'),
        'smtp_port': int(os.getenv('SMTP_PORT', 587)),
        'smtp_user': os.getenv('SMTP_USER'),
        'smtp_pass': smtp_pass,
        'from_email': os.getenv('FROM_EMAIL'),
        'from_name': os.getenv('FROM_NAME', 'Support'),
        'subject': os.getenv('EMAIL_SUBJECT', 'Newsletter'),
        'csv_file': os.getenv('CSV_FILE', 'emails.csv'),
        'html_template': os.getenv('HTML_TEMPLATE', 'template.html'),
        'rate_limit': int(os.getenv('RATE_LIMIT', '2'))
    }


def send_emails_async(recipients, html_template, config):

    global send_state

    send_state = {
        'is_sending': True,
        'total': len(recipients),
        'sent': 0,
        'failed': 0,
        'errors': [],
        'complete': False
    }

    if not all([config['smtp_host'], config['smtp_user'], config['smtp_pass']]):
        send_state['is_sending'] = False
        send_state['failed'] = len(recipients)
        send_state['complete'] = True
        return

    delay = 1.0 / config['rate_limit']

    try:
        server = smtplib.SMTP(str(config['smtp_host']), config['smtp_port'])
        server.starttls()
        server.login(str(config['smtp_user']), str(config['smtp_pass']))
    except Exception as e:
        send_state['is_sending'] = False
        send_state['failed'] = len(recipients)
        send_state['errors'].append({'email': 'SMTP Connection Error', 'error': str(e)}) # type: ignore
        send_state['complete'] = True
        return

    for recipient in recipients:

        try:

            html = personalize_html(html_template, recipient['name'])
            
            msg = MIMEMultipart('alternative')
            msg['Subject'] = config['subject']
            msg['From'] = f"{config['from_name']} <{config['from_email']}>"
            msg['To'] = recipient['email']

            html_part = MIMEText(html, 'html')
            msg.attach(html_part)

            server.send_message(msg)

            send_state['sent'] += 1 # type: ignore

        except Exception as e:

            send_state['failed'] += 1 # type: ignore
            send_state['errors'].append({ # type: ignore
                'email': recipient['email'],
                'error': str(e)
            })

        time.sleep(delay)

    try:
        server.quit()
    except:
        pass

    send_state['is_sending'] = False
    send_state['complete'] = True

# -----------------------------
# MAIN BULK EMAIL UI
# -----------------------------

@app.route('/index')
def index(template_name="index.html"):
    if not session.get('role'):
        return render_template("login.html")

    config = get_config()

    errors = []

    if not all([config['smtp_host'], config['smtp_user'], config['smtp_pass']]):
        errors.append('SMTP Credentials not configured')

    if not config['from_email']:
        errors.append('FROM_EMAIL not configured')

    files_status = {
        'csv': Path(config['csv_file']).exists(),
        'template': Path(config['html_template']).exists()
    }

    recipients = []
    invalid_emails = []

    if files_status['csv']:
        try:
            recipients, invalid_emails = load_csv(config['csv_file'])
        except Exception as e:
            errors.append(str(e))

    email_preview_html = ""

    if files_status['template']:

        html = load_html_template(config['html_template'])

        sample_name = recipients[0]['name'] if recipients else "John Doe"

        email_preview_html = personalize_html(html, sample_name)
        
    role = session.get('role', 'employee')

    return render_template(
        template_name,
        config=config,
        errors=errors,
        files_status=files_status,
        recipients=recipients,
        total_recipients=len(recipients),
        invalid_emails=invalid_emails,
        send_state=send_state,
        email_preview_html=email_preview_html,
        role=role,
        email=session.get('email')
    )

# ✅ Get template HTML for editor
@app.route('/get-template', methods=['GET'])
def get_template():
    config = get_config()
    try:
        html = load_html_template(config['html_template'])
        return jsonify({"html": html})
    except Exception as e:
        return jsonify({"html": "", "error": str(e)})


# ✅ Save edited template HTML to file
@app.route('/save-template', methods=['POST'])
def save_template():
    config = get_config()
    html = request.json.get("html", "")
    try:
        with open(config['html_template'], 'w', encoding='utf-8') as f:
            f.write(html)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route('/preview', methods=['GET'])
def get_preview():
    config = get_config()
    from_name = request.args.get('from_name', config['from_name'])
    subject = request.args.get('subject', config['subject'])
    
    html = ""
    try:
        html = load_html_template(config['html_template'])
        recipients, _ = load_csv(config['csv_file'])
        sample_name = recipients[0]['name'] if recipients else "John Doe"
        html = personalize_html(html, sample_name)
    except Exception:
        pass
        
    return jsonify({
        "from": f"{from_name} <{config['from_email']}>",
        "subject": subject,
        "pdf_name": os.getenv("PDF_ORIGINAL_NAME", config.get("pdf_file", "None")),
        "html": html
    })

@app.route('/send', methods=['POST'])
def send():

    global send_state

    if send_state['is_sending']:
        return jsonify({'error': 'Already sending emails'}), 400

    config = get_config()

    recipients, _ = load_csv(config['csv_file'])

    html_template = load_html_template(config['html_template'])

    thread = Thread(
        target=send_emails_async,
        args=(recipients, html_template, config)
    )

    thread.start()

    return jsonify({'status': 'started'})


@app.route('/status')
def status():
    return jsonify(send_state)


# -----------------------------
# START SERVER
# -----------------------------

if __name__ == '__main__':

    app.run(
        host='0.0.0.0',
        port=5000,
        debug=True
    )