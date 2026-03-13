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
import resend

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
    resend.api_key = os.getenv('RESEND_API_KEY')
    from_email = os.getenv('FROM_EMAIL')
    from_name = os.getenv('FROM_NAME', 'System')

    if not resend.api_key or not from_email:
        print("Resend Credentials missing. Cannot send system email.")
        return False

    try:
        r = resend.Emails.send({
            "from": f"{from_name} <{from_email}>",
            "to": to_email,
            "subject": subject,
            "html": body_html
        })
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
    elif role == 'user':
        return redirect("/dashboard")
    return render_template("login.html")


@app.route("/admin-dashboard")
def admin_dashboard():
    if session.get('role') != 'admin':
        return redirect("/dashboard")
    return index("index.html")


@app.route("/dashboard")
def user_dashboard():
    if session.get('role') == 'admin':
        return redirect("/admin-dashboard")
    if not session.get('role'):
        return redirect("/")
    return index("user.html")


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
    role = data.get("role", "user")
    
    if not email:
        return jsonify({"success": False, "error": "Email is required"}), 400
        
    db.users.update_one(
        {"email": email},
        {"$set": {"approved": int(approved), "role": role}},
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
    role = data.get("role")
    
    if not email or approved is None:
        return jsonify({"success": False, "error": "Email and approved status are required"}), 400
        
    update_data = {"approved": int(approved)}
    if role:
        update_data["role"] = role

    db.users.update_one(
        {"email": email},
        {"$set": update_data}
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
    
    if not html_content and not user_prompt:
        return jsonify({"success": False, "error": "HTML content or prompt is required"}), 400
    
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
    
    # Dynamic System Instructions and User Content
    if not html_content or not html_content.strip():
        # Generate fresh template
        system_instructions = "You are an expert professional email template designer. Generate a COMPLETE, FULL-LENGTH, HIGHLY PROFESSIONAL HTML email template with inline CSS. Return ONLY raw HTML code without markdown formatting."
        user_content = f"Create a complete professional HTML email template: {user_prompt}"
    else:
        # Enhance existing template
        system_instructions = (
            "You are a professional email template designer. Modify the provided HTML based on the user instructions. "
            "Maintain the overall structure but apply the requested changes. Return ONLY raw HTML code without markdown formatting."
        )
        user_content = f"Modify this HTML email template based on this instruction: {user_prompt}\n\nHTML:\n{html_content}"
    
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": system_instructions
            },
            {
                "role": "user",
                "content": user_content
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
            session['role'] = 'user'
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
                f"<p>User <b>{email}</b> has requested user access to the system. Please login to the dashboard and approve them if authorized.</p>"
            )
    
    # Notify User
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
    
    # Notify User they are approved
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
    return {
        'from_email': os.getenv('FROM_EMAIL'),
        'from_name': os.getenv('FROM_NAME', 'Support'),
        'subject': os.getenv('EMAIL_SUBJECT', 'Newsletter'),
        'csv_file': os.getenv('CSV_FILE'),
        'html_template': os.getenv('HTML_TEMPLATE'),
        'rate_limit': int(os.getenv('RATE_LIMIT', '2'))
    }


def send_emails_async(recipients, html_template, config, attachments=None):

    global send_state

    send_state = {
        'is_sending': True,
        'total': len(recipients),
        'sent': 0,
        'failed': 0,
        'errors': [],
        'complete': False
    }

    resend.api_key = os.getenv('RESEND_API_KEY')
    if not resend.api_key:
        send_state['is_sending'] = False
        send_state['failed'] = len(recipients)
        send_state['complete'] = True
        return

    delay = 1.0 / config['rate_limit']

    for recipient in recipients:
        try:
            html = personalize_html(html_template, recipient['name'])
            
            email_params = {
                "from": f"{config['from_name']} <{config['from_email']}>",
                "to": recipient['email'],
                "subject": config['subject'],
                "html": html
            }

            if attachments:
                email_params["attachments"] = attachments

            r = resend.Emails.send(email_params)

            send_state['sent'] += 1 # type: ignore

        except Exception as e:
            send_state['failed'] += 1 # type: ignore
            send_state['errors'].append({ # type: ignore
                'email': recipient['email'],
                'error': str(e)
            })

        time.sleep(delay)

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

    if not os.getenv('RESEND_API_KEY'):
        errors.append('RESEND_API_KEY not configured')

    if not config['from_email']:
        errors.append('FROM_EMAIL not configured')

    user_data = db.user_data.find_one({"email": session.get('email')}) or {}
    recipients = user_data.get('recipients', [])
    saved_template = user_data.get('template', '')
    
    files_status = {
        'csv': bool(recipients),
        'template': bool(saved_template),
        'pdf': bool(user_data.get('pdf_filename')),
        'image': bool(user_data.get('image_filename')),
        'pdf_filename': user_data.get('pdf_filename', ''),
        'image_filename': user_data.get('image_filename', '')
    }

    invalid_emails = []

    email_preview_html = ""

    if files_status['template']:
        sample_name = recipients[0]['name'] if recipients else "John Doe"
        email_preview_html = personalize_html(saved_template, sample_name)
        
    role = session.get('role', 'user')

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
@app.route('/upload-csv', methods=['POST'])
def upload_csv():
    if not session.get('role'):
        return jsonify({"error": "Login required"}), 403
    
    if 'csv_file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    
    file = request.files['csv_file']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400
    
    try:
        content = file.read().decode('utf-8')
        reader = csv.DictReader(content.splitlines())
        recipients = []
        for row in reader:
            email = row.get('email', '').strip()
            name = row.get('name', '').strip()
            if email and validate_email(email):
                recipients.append({'email': email, 'name': name})
        
        db.user_data.update_one(
            {"email": session['email']},
            {"$set": {"recipients": recipients}},
            upsert=True
        )
        return jsonify({"success": True, "total": len(recipients)})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/upload-pdf', methods=['POST'])
def upload_pdf():
    if not session.get('role'):
        return jsonify({"error": "Login required"}), 403
    
    if 'pdf_file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    
    file = request.files['pdf_file']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400
    
    try:
        content = file.read()
        base64_content = base64.b64encode(content).decode('utf-8')
        
        db.user_data.update_one(
            {"email": session['email']},
            {"$set": {
                "pdf_base64": base64_content,
                "pdf_filename": file.filename
            }},
            upsert=True
        )
        return jsonify({"success": True, "filename": file.filename})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/upload-image', methods=['POST'])
def upload_image():
    if not session.get('role'):
        return jsonify({"error": "Login required"}), 403
    
    if 'image_file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    
    file = request.files['image_file']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400
    
    try:
        content = file.read()
        base64_content = base64.b64encode(content).decode('utf-8')
        
        db.user_data.update_one(
            {"email": session['email']},
            {"$set": {
                "image_base64": base64_content,
                "image_filename": file.filename
            }},
            upsert=True
        )
        return jsonify({"success": True, "filename": file.filename})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/delete-pdf', methods=['DELETE'])
def delete_pdf():
    if not session.get('role'):
        return jsonify({"error": "Login required"}), 403
    
    try:
        db.user_data.update_one(
            {"email": session['email']},
            {"$unset": {
                "pdf_base64": "",
                "pdf_filename": ""
            }}
        )
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/delete-image', methods=['DELETE'])
def delete_image():
    if not session.get('role'):
        return jsonify({"error": "Login required"}), 403
    
    try:
        db.user_data.update_one(
            {"email": session['email']},
            {"$unset": {
                "image_base64": "",
                "image_filename": ""
            }}
        )
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# ✅ Update a recipient
@app.route('/update-recipient', methods=['PUT'])
def update_recipient():
    if not session.get('role'):
        return jsonify({"error": "Login required"}), 403
    
    data = request.json
    old_email = data.get('old_email')
    new_email = data.get('new_email')
    new_name = data.get('new_name')

    if not all([old_email, new_email, new_name]):
        return jsonify({"error": "Missing data"}), 400
    
    try:
        result = db.user_data.update_one(
            {"email": session['email'], "recipients.email": old_email},
            {"$set": {
                "recipients.$.email": new_email,
                "recipients.$.name": new_name
            }}
        )
        if result.modified_count > 0:
            return jsonify({"success": True})
        return jsonify({"error": "Recipient not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# ✅ Add a single recipient
@app.route('/add-recipient', methods=['POST'])
def add_recipient():
    if not session.get('role'):
        return jsonify({"error": "Login required"}), 403

    data = request.json
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip()

    if not email:
        return jsonify({"success": False, "error": "Email is required"}), 400

    if not validate_email(email):
        return jsonify({"success": False, "error": "Invalid email address"}), 400

    try:
        # Check for duplicate
        user_data = db.user_data.find_one({"email": session['email']}) or {}
        existing = user_data.get('recipients', [])
        if any(r.get('email', '').lower() == email.lower() for r in existing):
            return jsonify({"success": False, "error": "Recipient with this email already exists"}), 409

        db.user_data.update_one(
            {"email": session['email']},
            {"$push": {"recipients": {"name": name, "email": email}}},
            upsert=True
        )
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ✅ Delete a recipient
@app.route('/delete-recipient', methods=['DELETE'])
def delete_recipient():
    if not session.get('role'):
        return jsonify({"error": "Login required"}), 403
    
    data = request.json
    email = data.get('email')

    if not email:
        return jsonify({"error": "Email required"}), 400
    
    try:
        result = db.user_data.update_one(
            {"email": session['email']},
            {"$pull": {"recipients": {"email": email}}}
        )
        if result.modified_count > 0:
            return jsonify({"success": True})
        return jsonify({"error": "Recipient not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# ✅ Get template HTML for editor
@app.route('/get-template')
def get_template():
    if not session.get('role'):
        return jsonify({"error": "Login required"}), 403
    user_data = db.user_data.find_one({"email": session.get('email')}) or {}
    html = user_data.get('template', '')
    return jsonify({"html": html})


# ✅ Save edited template HTML to file
@app.route('/save-template', methods=['POST'])
def save_template():
    if not session.get('role'):
        return jsonify({"error": "Login required"}), 403
    html = request.json.get("html", "")
    db.user_data.update_one(
        {"email": session['email']},
        {"$set": {"template": html}},
        upsert=True
    )
    return jsonify({"success": True})


@app.route('/has-template')
def has_template():
    if not session.get('role'):
        return jsonify({"error": "Login required"}), 403
    user_data = db.user_data.find_one({"email": session.get('email')}) or {}
    has_template = bool(user_data.get('template', ''))
    has_recipients = bool(user_data.get('recipients', []))
    return jsonify({"has_template": has_template, "has_recipients": has_recipients})


@app.route('/preview', methods=['GET'])
def get_preview():
    config = get_config()
    from_name = request.args.get('from_name', config['from_name'])
    subject = request.args.get('subject', config['subject'])
    
    html = ""
    try:
        user_data = db.user_data.find_one({"email": session.get('email')}) or {}
        html = user_data.get('template', '')
        recipients = user_data.get('recipients', [])
        sample_name = recipients[0]['name'] if recipients else "John Doe"
        if html:
            html = personalize_html(html, sample_name)
    except Exception:
        pass
        
    return jsonify({
        "from": f"{from_name} <{config['from_email']}>",
        "subject": subject,
        "pdf_name": user_data.get('pdf_filename', 'None'),
        "image_name": user_data.get('image_filename', 'None'),
        "html": html
    })

@app.route('/send', methods=['POST'])
def send():

    global send_state

    if send_state['is_sending']:
        return jsonify({'error': 'Already sending emails'}), 400

    config = get_config()

    user_data = db.user_data.find_one({"email": session.get('email')}) or {}
    recipients = user_data.get('recipients', [])

    html_template = user_data.get('template', '')
    if not html_template:
        return jsonify({'error': 'No saved template found.'}), 400

    attachments = []
    if user_data.get('pdf_base64'):
        attachments.append({
            "filename": user_data.get('pdf_filename', 'attachment.pdf'),
            "content": user_data['pdf_base64'],
            "content_type": "application/pdf"
        })
    
    if user_data.get('image_base64'):
        attachments.append({
            "filename": user_data.get('image_filename', 'image.png'),
            "content": user_data['image_base64'],
            "content_type": "image/png"
        })

    thread = Thread(
        target=send_emails_async,
        args=(recipients, html_template, config, attachments)
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