import sqlite3
import json
import re
import io
import pandas as pd
from reportlab.lib.units import inch
import datetime
import smtplib
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph
from reportlab.lib.styles import getSampleStyleSheet
import openai
from datetime import timedelta
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from io import BytesIO
from flask import make_response
from email.mime.text import MIMEText

from flask import make_response

from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, PageBreak, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import letter, landscape

DB_NAME = 'projects.db'

DIVISIONS = [
    "Concrete", "Masonry", "Metals", "Wood, Plastics, and Composites",
    "Thermal and Moisture Protection", "Openings", "Finishes", "Specialties",
    "Equipment", "Furnishings", "Special Construction", "Conveying Equipment",
    "Fire Suppression", "Plumbing", "Heating, Ventilating, and Air Conditioning",
    "Integrated Automation", "Electrical", "Communications", "Electronic Safety and Security",
    "Earthwork", "Exterior Improvements", "Utilities", "Transportation", "Waterway and Marine Construction",
    "Process Integration", "Material Processing and Handling Equipment", "Process Heating, Cooling, and Drying Equipment",
    "Process Gas and Liquid Handling, Purification, and Storage Equipment", "Pollution and Waste Control Equipment",
    "Industry-Specific Manufacturing Equipment", "Water and Wastewater Equipment", "Electrical Power Generation"
]

def filter_projects_by_division(projects, division_names=None):
    filtered_projects = []
    for project in projects:
        id, name, owner_emails, description, divisions_data_json = project
        divisions_data = json.loads(divisions_data_json)

        if division_names:
            filtered_divisions = {key: value for key, value in divisions_data.items() if key in division_names}
        else:
            filtered_divisions = divisions_data

        filtered_projects.append((id, name, owner_emails, description, json.dumps(filtered_divisions)))

    return filtered_projects

def get_roles():
    return ['General Contractor', 'Subcontractor', 'Supplier', 'Admin/Support', 'Developer']

def fetch_projects_by_name(project_name=None):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    query = "SELECT id, name, owner_emails, description, divisions_data FROM Project"
    parameters = []

    if project_name:
        query += " WHERE name = ?"
        parameters.append(project_name)

    cursor.execute(query, parameters)
    projects = cursor.fetchall()

    conn.close()
    return projects


def apply_risk_analysis_filter(projects):
    for project in projects:
        divisions_data = json.loads(project[4])  # Assuming divisions_data is at index 4

        for division, data in divisions_data.items():
            for entry in data.get('entries', []):
                needed_onsite = datetime.datetime.strptime(entry.get('neededOnsite', '1900-01-01'), '%Y-%m-%d').date()
                eta_delivery = datetime.datetime.strptime(entry.get('etaDelivery', '1900-01-01'), '%Y-%m-%d').date()

                if eta_delivery > needed_onsite:
                    entry['late'] = True  # Mark entry as late

        project[4] = json.dumps(divisions_data)  # Update divisions_data with risk analysis

    return projects

def apply_near_critical_filter(projects, reference_date, weeks=6):
    critical_period = timedelta(weeks=weeks)

    for project in projects:
        divisions_data = json.loads(project[4])  # Assuming divisions_data is at index 4

        for division, data in divisions_data.items():
            for entry in data.get('entries', []):
                needed_onsite = datetime.datetime.strptime(entry.get('neededOnsite', '1900-01-01'), '%Y-%m-%d').date()
                if reference_date <= needed_onsite <= (reference_date + critical_period):
                    entry['near_critical'] = True  # Mark entry as near critical

        project[4] = json.dumps(divisions_data)  # Update divisions_data with near critical info

    return projects


def filter_divisions_by_date_range(projects, start_date=None, end_date=None):
    if not start_date and not end_date:
        return projects  # No filtering needed

    filtered_projects = []
    for project in projects:
        id, name, owner_emails, description, divisions_data_json = project
        divisions_data = json.loads(divisions_data_json)

        for division, data in divisions_data.items():
            filtered_entries = []
            for entry in data.get('entries', []):
                needed_onsite = datetime.datetime.strptime(entry.get('neededOnsite', '1900-01-01'), '%Y-%m-%d').date()

                if start_date and needed_onsite < start_date:
                    continue
                if end_date and needed_onsite > end_date:
                    continue

                filtered_entries.append(entry)

            divisions_data[division]['entries'] = filtered_entries

        filtered_projects.append((id, name, owner_emails, description, json.dumps(divisions_data)))

    return filtered_projects

def initialize_database():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Create Project Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS Project (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        owner_emails TEXT,
        description TEXT,
        divisions_data TEXT
    )
    ''')
    conn.commit()
    conn.close()

def create_new_project(name, owner_email, description, custom_divisions, email_division_map):
    divisions = {}
    user_division_map = {}

    # Helper function to process divisions and emails/roles
    def process_divisions(divisions_map):
        for division, emails_roles in divisions_map.items():
            if division not in divisions:
                divisions[division] = {
                    "allowed_emails": [{"email": owner_email, "role": "General Contractor"}],
                    "entries": []
                }
            for email_role in emails_roles:
                email = email_role["email"]
                role = email_role["role"]
                if {"email": email, "role": role} not in divisions[division]["allowed_emails"]:
                    divisions[division]["allowed_emails"].append({"email": email, "role": role})
                if email != owner_email:
                    user_division_map.setdefault(email, {}).setdefault(division, role)

    # Process emailDivisionMap
    process_divisions(email_division_map)

    # Process customDivisions
    process_divisions(custom_divisions)

    # Database operations to insert the new project
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO Project (name, owner_emails, description, divisions_data) VALUES (?, ?, ?, ?)",
                       (name, owner_email, description, json.dumps(divisions)))
        conn.commit()
    finally:
        conn.close()

    # Send email to each invited user (except the owner)
    for user_email, divisions_roles in user_division_map.items():
        divisions = list(divisions_roles.keys())
        roles = list(divisions_roles.values())
        subject = f"You've been invited to project: {name}"
        body = f"You've been invited to project: {name}, in divisions: {', '.join(divisions)} with roles: {', '.join(roles)}."
        send_email(user_email, subject, body)


def delete_division(project_name, division_name):
    # Connect to the SQLite database
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    try:
        # Retrieve the current divisions_data for the project
        cursor.execute("SELECT divisions_data FROM Project WHERE name = ?", (project_name,))
        result = cursor.fetchone()
        if result:
            divisions_data = json.loads(result[0])

            # Delete the division if it exists
            if division_name in divisions_data:
                del divisions_data[division_name]

                # Write the updated divisions_data back to the database
                updated_divisions_data = json.dumps(divisions_data)
                cursor.execute("UPDATE Project SET divisions_data = ? WHERE name = ?", (updated_divisions_data, project_name))
                conn.commit()
                return True  # or some other success message
            else:
                return False  # or some other error message indicating division not found
        else:
            return False  # or some other error message indicating project not found

    except Exception as e:
        print(f"An error occurred: {e}")
        raise
    finally:
        conn.close()

def fetch_project_data_for_pdf(project_name):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT name, description, divisions_data FROM Project WHERE name = ?", (project_name,))
    project = cursor.fetchone()
    conn.close()

    if not project:
        return None, "Project not found."

    name, description, divisions_data_json = project
    divisions_data = json.loads(divisions_data_json)
    current_date = datetime.datetime.now().date()
    critical_period = timedelta(weeks=6)

    pdf_data = {'project_name': name, 'description': description, 'divisions': []}

    for division, details in divisions_data.items():
        entries = details.get('entries', [])
        formatted_entries = []
        for entry in entries:
            eta_delivery = datetime.datetime.strptime(entry.get('etaDelivery', ''), '%Y-%m-%d').date() if entry.get('etaDelivery') else None
            needed_on_site = datetime.datetime.strptime(entry.get('neededOnsite', ''), '%Y-%m-%d').date() if entry.get('neededOnsite') else None
            is_overdue = eta_delivery and needed_on_site and eta_delivery > needed_on_site
            is_near_critical = needed_on_site and current_date <= needed_on_site <= (current_date + critical_period)

            formatted_entry = {k: v for k, v in entry.items()}
            formatted_entry['is_overdue'] = is_overdue
            formatted_entry['is_near_critical'] = is_near_critical
            formatted_entries.append(formatted_entry)

        pdf_data['divisions'].append({'division_name': division, 'entries': formatted_entries})

    return pdf_data, None
def delete_project(project_name):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM Project WHERE name = ?", (project_name,))
        conn.commit()
        return True
    except Exception as e:
        print(f"An error occurred: {e}")
        return False
    finally:
        conn.close()

def send_status_notification(project_name, division_name, shipped_notifications, delivered_notifications):
    # create body of email
    subject = f"Status Update for Project: {project_name} Division: {division_name}"
    body = ""
    if shipped_notifications:
        body += "Items Shipped:\n"
        for item in shipped_notifications:
            body += f"- {item}\n"
        body += "\n"
    if delivered_notifications:
        body += "Items Delivered:\n"
        for item in delivered_notifications:
            body += f"- {item}\n"
        body += "\n"
    
    for person in get_emails_for_division(project_name, division_name):
        email = person['email']
        role = person['role']
        if role == 'General Contractor' or role == 'Subcontractor':
            send_email(email, subject, body)

def send_email(recipient, subject, body):
    sender = "mcaas.lol@gmail.com"
    password = "aifqdhottuxejjkk"  # App password or email password

    message = MIMEText(body)
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:  # Note SMTP_SSL here
        server.login(sender, password)
        server.sendmail(sender, recipient, message.as_string())

def log_action(user_email, action):
    with open('log.txt', 'a') as log_file:
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"{timestamp} - {user_email} - {action}\n"
        log_file.write(log_entry)

def get_project_id(project_name, requester_email):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("SELECT id, owner_emails FROM Project WHERE name = ?", (project_name,))
    row = cursor.fetchone()

    if row:
        project_id, owner_emails = row

        if requester_email in owner_emails.split(','):
            return project_id

    return None

def get_projects_for_email(email):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("SELECT name, owner_emails, divisions_data FROM Project")
    all_projects = cursor.fetchall()

    email_projects_divisions = {}

    for project_name, owner_emails, divisions_data_str in all_projects:
        divisions_data = json.loads(divisions_data_str)
        is_owner = email in owner_emails.split(',')

        # If email is the owner, automatically add all divisions
        if is_owner:
            email_projects_divisions[project_name] = (DIVISIONS, True)
            continue

        divisions_for_user = []
        for division, division_data in divisions_data.items():
            if email in division_data['allowed_emails']:
                divisions_for_user.append(division)
            # for newer projects where the email, role is a dictionary
        # If user has access to any division, add project with those divisions
        if divisions_for_user:
            email_projects_divisions[project_name] = (divisions_for_user, False)

    return email_projects_divisions

openai.api_key = 'sk-proj-ho5k3U6b3UGEFhBippZgT3BlbkFJsG3l4FN2jV6BMggYOTBP'
from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from io import BytesIO
from flask import make_response
def generate_pdf_with_gpt4(project_data, filename, summary_function):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter),
                            rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='Center', alignment=TA_CENTER))
    styles.add(ParagraphStyle(name='Left', alignment=TA_LEFT))

    elements = []

    # Add project title and description
    elements.append(Paragraph(f"Project: {project_data['project_name']}", styles['Title']))
    elements.append(Spacer(1, 12))
    elements.append(Paragraph(f"Description: {project_data['description']}", styles['Normal']))
    elements.append(Spacer(1, 24))

    for division in project_data['divisions']:
        elements.append(Paragraph(f"Division: {division['division_name']}", styles['Heading2']))
        elements.append(Spacer(1, 12))

        if division['entries']:
            division_summary = summary_function(division['division_name'], division['entries'])
            
            table_data, analysis = split_summary(division_summary)

            if table_data:
                table = create_table(table_data)
                elements.append(table)
                elements.append(Spacer(1, 12))

            if analysis:
                elements.append(Paragraph("Analysis:", styles['Heading3']))
                elements.append(Paragraph(analysis, styles['Normal']))

        else:
            elements.append(Paragraph("No entries for this division.", styles['Italic']))

        elements.append(Spacer(1, 24))

    doc.build(elements)
    buffer.seek(0)
    
    response = make_response(buffer.getvalue())
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    response.headers['Content-Type'] = 'application/pdf'
    
    return response
def split_summary(summary):
    lines = summary.split('\n')
    table_data = []
    analysis = ""
    in_table = False

    for line in lines:
        stripped_line = line.strip()
        if stripped_line.startswith("|") or stripped_line.startswith("+"):
            in_table = True
            if stripped_line.startswith("|"):
                row = [cell.strip() for cell in stripped_line.split("|") if cell.strip()]
                table_data.append(row)
        elif in_table and not stripped_line:
            in_table = False
        elif not in_table and stripped_line:
            analysis += line + "\n"

    return table_data, analysis.strip()
def create_table(data):
    if not data:
        return None

    # Calculate the available width for the table
    available_width = letter[0] - 60  # Subtracting 60 points for margins

    # Determine the number of columns
    num_cols = len(data[0])

    # Calculate the width for each column
    col_widths = [available_width / num_cols] * num_cols

    table = Table(data, colWidths=col_widths)

    # Define table style
    style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8),  # Reduced font size for header
        ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 7),  # Reduced font size for content
        ('TOPPADDING', (0, 1), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 3),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black)
    ])
    table.setStyle(style)

    # Enable word wrapping for all cells
    for i in range(len(data)):
        for j in range(len(data[i])):
            table._cellvalues[i][j] = Paragraph(str(data[i][j]), getSampleStyleSheet()['Normal'])

    return table

def get_gpt4_summary(division_name, entries):
    # Generate a summary using gpt-4-turbo
    prompt = f"""
    You are an AI specialized in generating concise summaries for construction project reports.
    Analyze the following division data and generate a structured summary that focuses on the status of items (Late, On Time, Close).

    Division Name: {division_name}

    Entries: 
    {json.dumps(entries, indent=2)}

    Your summary should include:
    - The status of each item based on its needed on-site date and estimated arrival date:
      - "Late" if the estimated arrival date is after the needed on-site date.
      - "On Time" if the estimated arrival date is on or before the needed on-site date.
      - "Close" if the needed on-site date is within 3 days of the estimated arrival date.
    """
    response = openai.ChatCompletion.create(
        model="gpt-4-turbo",
        messages=[
            {"role": "system", "content": "You are an AI specialized in generating concise summaries for construction project reports."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=300
    )
    summary = response.choices[0]['message']['content'].strip()
    
    return summary

def get_emails_for_division(project_name, division_name):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("SELECT divisions_data FROM Project WHERE name = ?", (project_name,))
    row = cursor.fetchone()

    if row:
        divisions_data = json.loads(row[0])
        allowed_emails = divisions_data.get(division_name, {}).get('allowed_emails', [])
        conn.close()
        return allowed_emails
    else:
        conn.close()
        return []

def get_role(email, project_name, division_name):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("SELECT owner_emails, divisions_data FROM Project WHERE name = ?", (project_name,))
    result = cursor.fetchone()

    if not result:
        return None

    owner_emails, divisions_data_str = result
    divisions_data = json.loads(divisions_data_str)
    
    try:
        items = divisions_data[division_name]['allowed_emails']
    except KeyError:
        return None

    for item in items:
        if item == email:
            # for old projects just make it so they have permissoins to view. This is just for people who've had access from 1.1
            return 'Subcontractor'
        if item['email'] == email:
            return item['role'] 

    return None

def db_get_division_data(project_id, division_name, user_email):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Assuming the table name is Project and it has a column named divisions_data
    cursor.execute("SELECT divisions_data FROM Project WHERE id = ?", (project_id,))
    row = cursor.fetchone()
    conn.close()

    if row:
        # Parse the JSON stored in the database
        divisions_data = json.loads(row[0])

        # Check if the user is allowed to access the division data
        division_info = divisions_data.get(division_name)
        if division_info and (user_email in division_info["allowed_emails"] or user_email == 'owner@example.com'):

            return division_info

        else:
            raise ValueError("User does not have access to this division or division does not exist.")

    else:
        raise ValueError("Project not found.")

# data_access.py
def get_project_info(project_name):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, owner_emails, description, divisions_data FROM Project WHERE name = ?", (project_name,))
        result = cursor.fetchone()
        if result:
            id, owner_emails, description, divisions_data = result
            project_info = {
                'success': True,
                'project_id': id,
                'owner_email': owner_emails.split(',')[0],  # Assuming the first email is the owner's email
                'description': description,
                'divisions': json.loads(divisions_data)  # Assuming divisions_data is a JSON string
            }
            return project_info
        else:
            return {'success': False, 'error': 'Project not found'}
    except Exception as e:
        print(f"An error occurred: {e}")
        return {'success': False, 'error': str(e)}
    finally:
        conn.close()

def get_divisions_for_project(project_name, requester_email):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("SELECT divisions_data FROM Project WHERE name = ?", (project_name,))
    row = cursor.fetchone()
    conn.close()

    if row:
        divisions_data = json.loads(row[0])

        accessible_divisions = [
            division for division in divisions_data
            if requester_email.strip().lower() in [email.strip().lower() for email in divisions_data[division].get('allowed_emails', [])]
        ]

        return {'success': True, 'divisions': accessible_divisions}
    else:
        return {'success': False, 'error': 'Project not found.'}

def edit_division_entry(project_name, editor_email, target_division, update_data):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("SELECT owner_emails, divisions_data FROM Project WHERE name = ?", (project_name,))
    project_data = cursor.fetchone()

    if not project_data:
        print(f"Project '{project_name}' not found!")
        conn.close()
        return False

    owner_emails, divisions_data_str = project_data
    divisions_data = json.loads(divisions_data_str)

    allowed_emails = divisions_data[target_division]['allowed_emails']

    if editor_email in allowed_emails or editor_email in owner_emails.split(','):
        entries = divisions_data[target_division]['entries']
        for entry in entries:
            if entry['name'] == update_data['name']:
                entry.update({
                    'name': update_data.get('name', entry['name']),
                    'quantity': update_data.get('quantity', entry['quantity']),
                    'unit': update_data.get('unit', entry['unit']),
                    'leadTime': update_data.get('leadTime', entry['leadTime']),
                    'neededOnsite': update_data.get('neededOnsite', entry['neededOnsite']),
                    'manufacturingTime': update_data.get('manufacturingTime', entry['manufacturingTime']),
                    'etaDelivery': update_data.get('etaDelivery', entry['etaDelivery']),
                    'manufacturer': update_data.get('manufacturer', entry['manufacturer']),
                    'fabrication': update_data.get('fabrication', entry['fabrication']),
                    'deliveryLocation': update_data.get('deliveryLocation', entry['deliveryLocation']),
                    'trackingNumber': update_data.get('trackingNumber', entry['trackingNumber']),
                    'notes': update_data.get('notes', entry['notes']),
                    'shipped': update_data.get('shipped', entry['shipped']),
                    'delivered': update_data.get('delivered', entry['delivered']),
                    'file': update_data.get('file', entry.get('file', None)),
                    'attachFile': update_data.get('attachFile', entry.get('attachFile', None)),
                })
                break

        updated_divisions_data_str = json.dumps(divisions_data)
        print("going to commit to db")
        cursor.execute("UPDATE Project SET divisions_data = ? WHERE name = ?", (updated_divisions_data_str, project_name))
        print("commited to db")
        conn.commit()

        conn.close()
        return True
    else:
        conn.close()
        return False


styles = getSampleStyleSheet()

def get_divisions_for_email(project_name, email):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT divisions_data FROM Project WHERE name = ?", (project_name,))
    data = cursor.fetchone()

    if not data:
        return []

    divisions_data = json.loads(data[0])
    allowed_divisions = [division for division, details in divisions_data.items() if email in details["allowed_emails"]]

    conn.close()
    return allowed_divisions

def display_division_data(project_name, email, target_division):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Fetch the project's data
    cursor.execute("SELECT owner_emails, divisions_data FROM Project WHERE name = ?", (project_name,))
    project_data = cursor.fetchone()

    if not project_data:
        print(f"Project '{project_name}' not found!")
        conn.close()
        return

    owner_emails, divisions_data_str = project_data
    divisions_data = json.loads(divisions_data_str)

    # Check if the provided email has access to the target_division or is the project owner
    if email in divisions_data[target_division]['allowed_emails'] or email in owner_emails.split(','):
        print(f"Data for division '{target_division}' in project '{project_name}':")
        for entry in divisions_data[target_division]['entries']:
            print(entry)
    else:
        print(f"User '{email}' doesn't have the permission to view '{target_division}' in project '{project_name}'.")

    conn.close()

def add_new_division(project_name, division_name, user_email):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Fetch and update project's divisions_data
    cursor.execute("SELECT divisions_data FROM Project WHERE name = ?", (project_name,))
    result = cursor.fetchone()

    if result:
        divisions_data = json.loads(result[0])

        # Add new division if it doesn't exist
        if division_name not in divisions_data:
            divisions_data[division_name] = {"allowed_emails": [{'email': user_email, 'role': "General Contractor"}], "entries": []}
            cursor.execute("UPDATE Project SET divisions_data = ? WHERE name = ?", (json.dumps(divisions_data), project_name))
            conn.commit()
            conn.close()
            return True
        else:
            conn.close()
            return False  # Division already exists
    else:
        conn.close()
        return False  # Project not found

def fetch_division_data(project_name, division_name, user_email):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("SELECT divisions_data FROM Project WHERE name = ?", (project_name,))
    row = cursor.fetchone()

    conn.close()

    if row:
        divisions_data = json.loads(row[0])
        if division_name in divisions_data:
            data = divisions_data[division_name]['allowed_emails']
            for item in data:
                if user_email == item:
                    # handle if the user has an old project db
                    return divisions_data[division_name]['entries'], None
                if user_email == item['email']:
                    return divisions_data[division_name]['entries'], None
            else:
                return None, "Access Denied: Your email is not allowed to access this division."
        else:
            return None, "Error: Division not found."
    else:
        return None, "Error: Project not found."


def generate_csv(all_entries):
    if all_entries:
        # Convert all_entries to a DataFrame
        df = pd.DataFrame(all_entries)

        # Ensure 'Needed On-site' and 'ETA Delivery' are in datetime format
        # This step is optional if they are already in datetime format
        # df['Needed On-site'] = pd.to_datetime(df['Needed On-site'], errors='coerce')
        # df['ETA Delivery'] = pd.to_datetime(df['ETA Delivery'], errors='coerce')

        # Convert DataFrame to CSV string
        csv_string = df.to_csv(index=False, date_format='%Y-%m-%d')

        return csv_string
    else:
        return "No data to export."

def generate_pdf(project_data, filename):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter))
    styles = getSampleStyleSheet()
    elements = []

    # Adding Project Title and Description
    elements.append(Paragraph(f"Project: {project_data['project_name']}", styles['Title']))
    elements.append(Spacer(1, 12))
    elements.append(Paragraph(f"Description: {project_data['description']}", styles['Normal']))
    elements.append(Spacer(1, 24))

    current_date = datetime.datetime.today().date()

    # Processing each division
    for division in project_data['divisions']:
        elements.append(Paragraph(f"Division: {division['division_name']}", styles['Heading2']))
        elements.append(Spacer(1, 12))

        if division['entries']:
            # Table Headers
            table_data = [['Name/Description', 'Quantity', 'Lead Time (Days)', 'Needed On-Site', 'Manufacturing Time (Days)', 'ETA Delivery', 'Manufacturer']]
            styles_list = [
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('ROWBACKGROUNDS', (0, 0), (-1, 0), [colors.grey]),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER')
            ]

            for i, entry in enumerate(division['entries']):
                eta_delivery = datetime.datetime.strptime(entry['etaDelivery'], '%Y-%m-%d').date() if entry['etaDelivery'] else None
                needed_on_site = datetime.datetime.strptime(entry['neededOnsite'], '%Y-%m-%d').date() if entry['neededOnsite'] else None
                row = [
                    entry['name'],
                    entry['quantity'],
                    entry['leadTime'],
                    entry['neededOnsite'],
                    entry['manufacturingTime'],
                    entry['etaDelivery'],
                    entry['manufacturer']
                ]

                # Check for near critical (within 6 weeks) and overdue items
                if needed_on_site:
                    if eta_delivery and eta_delivery > needed_on_site:
                        row[5] += " (Late)"
                        # Add style to make overdue items red
                        styles_list.append(('TEXTCOLOR', (5, i+1), (5, i+1), colors.red))
                    if current_date <= needed_on_site <= (current_date + timedelta(weeks=6)):
                        row[3] += " (Near Critical)"

                table_data.append(row)

            # Creating table for division
            table = Table(table_data, repeatRows=1)
            table.setStyle(TableStyle(styles_list))
            elements.append(table)
        else:
            elements.append(Paragraph("No entries for this division.", styles['Italic']))

        elements.append(Spacer(1, 24))

    doc.build(elements)
    buffer.seek(0)
    response = make_response(buffer.getvalue())
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    response.headers['Content-Type'] = 'application/pdf'
    return response

def fetch_project_data_for_csv(project_name, user_email):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Query to select the project's division data
    cursor.execute("SELECT divisions_data FROM Project WHERE name = ?", (project_name,))
    row = cursor.fetchone()

    # Close the database connection
    conn.close()

    if row:
        divisions_data = json.loads(row[0])
        all_entries = []

        # Iterate through all divisions to collect entries
        for division_name, division_info in divisions_data.items():
            if user_email in division_info['allowed_emails']:
                for entry in division_info['entries']:
                    # Add division name to each entry for clarity in the CSV
                    entry_with_division = entry.copy()
                    entry_with_division['Division'] = division_name
                    all_entries.append(entry_with_division)
        print(all_entries)

        if not all_entries:
            return None, "Access Denied: Your email is not allowed to access this project or no entries found."

        return all_entries, None
    else:
        return None, "Error: Project not found."

def add_email_to_division(project_name, division_name, adding_email, new_email):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT owner_emails, divisions_data FROM Project WHERE name = ?", (project_name,))
    data = cursor.fetchone()

    if not data:
        print("Project not found.")
        return

    owner_emails, divisions_data_str = data
    divisions_data = json.loads(divisions_data_str)

    # Check if the adding_email has permission or is the project owner
    if adding_email in divisions_data[division_name]["allowed_emails"] or adding_email in owner_emails.split(','):
        if new_email not in divisions_data[division_name]["allowed_emails"]:
            divisions_data[division_name]["allowed_emails"].append(new_email)
            cursor.execute("UPDATE Project SET divisions_data = ? WHERE name = ?",
                           (json.dumps(divisions_data), project_name))
            conn.commit()
            print(f"{new_email} added to {division_name}.")
            conn.close()
            return {'success': True, 'error': False}
        else:
            print(f"{new_email} already has access to {division_name}.")
            conn.close()
            return {'success': False, "error": "Email already has access."}
    else:
        print(f"{adding_email} does not have permission to add emails to {division_name}.")
        conn.close()
        return {'success': False, "error": "Permission denied."}

def add_emails_to_division(project_name, division_name, new_emails):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Fetch the project's data
    cursor.execute("SELECT divisions_data FROM Project WHERE name = ?", (project_name,))
    project_data = cursor.fetchone()

    if not project_data:
        print(f"Project '{project_name}' not found.")
        conn.close()
        return False

    divisions_data = json.loads(project_data[0])

    if division_name in divisions_data:
        # Add each new email to the division's allowed_emails list if not already present
        for email in new_emails:
            # Check if email is a string or a dictionary
            if isinstance(email, str):
                # Check if the email is not already present as a string in allowed_emails
                if email not in [entry if isinstance(entry, str) else entry.get('email') for entry in divisions_data[division_name]["allowed_emails"]]:
                    divisions_data[division_name]["allowed_emails"].append(email)
            elif isinstance(email, dict):
                email_value = email.get('email')
                # Check if the dictionary email is not already present in allowed_emails
                if email_value and email_value not in [entry if isinstance(entry, str) else entry.get('email') for entry in divisions_data[division_name]["allowed_emails"]]:
                    divisions_data[division_name]["allowed_emails"].append(email)


        # Update the divisions_data in the database
        cursor.execute("UPDATE Project SET divisions_data = ? WHERE name = ?",
                       (json.dumps(divisions_data), project_name))
        conn.commit()
        print(f"Emails added to division '{division_name}' in project '{project_name}'.")
        conn.close()
        return True
    else:
        print(f"Division '{division_name}' not found in project '{project_name}'.")
        conn.close()
        return False

def get_all_users():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("SELECT owner_emails, divisions_data FROM Project")
    all_projects = cursor.fetchall()

    all_users = []
    for project in all_projects:
        owner_emails, divisions_data = project[0], project[1]
        all_users.append(owner_emails)
        divisions_data = json.loads(divisions_data)
        for division in divisions_data:
            for email in divisions_data[division]['allowed_emails']:
                if isinstance(email, dict):
                    all_users.append(email)
                else:
                    all_users.append(email)

    conn.close()
    return all_users

def update_division_entries(project_name, division_name, new_entries):
    try:
        conn = sqlite3.connect(DB_NAME)  # Ensure this is the correct path to your database
        cursor = conn.cursor()

        # Fetch the existing project data
        cursor.execute("SELECT id, divisions_data FROM Project WHERE name = ?", (project_name,))
        row = cursor.fetchone()

        if row:
            # Parse the divisions_data
            divisions_data = json.loads(row[1])

            # Replace the specific division's entries
            if division_name in divisions_data:
                divisions_data[division_name]['entries'] = new_entries  # Replacing existing entries

                # Convert back to JSON and update the database
                updated_divisions = json.dumps(divisions_data)
                cursor.execute("UPDATE Project SET divisions_data = ? WHERE id = ?", (updated_divisions, row[0]))
                conn.commit()

        conn.close()
    except Exception as e:
        print(f"Database error: {e}")
        raise


def default_data_addition(project_name):
    divisions = {
        "Existing Conditions": ["Wrecking Balls", "Jackhammers", "Explosives", "Contaminated Soil Treatment", "Hazardous Waste Disposal", "Theodolites", "GPS Survey Equipment", "Soil Stabilization Materials", "Site Remediation Chemicals", "De-watering Equipment"],
        "Concrete": ["Form Panels", "Form Ties", "Shoring", "Cement", "Aggregates", "Rebar", "Wire Mesh", "Curing Compounds", "Expansion Joints", "Concrete Admixtures", "Concrete Sealers", "Precast Concrete Elements", "Concrete Reinforcement Accessories"],
        "Masonry": ["Clay Bricks", "Concrete Blocks", "Premixed Mortar", "Mortar Additives", "Granite", "Limestone", "Masonry Ties", "Flashing", "Masonry Cleaning Agents", "Structural Clay Tile", "Stone Veneer", "Masonry Anchors"],
        "Metals": ["Beams", "Columns", "Roof Deck", "Floor Deck", "Ladders", "Railings", "Bolts", "Nuts", "Structural Steel", "Metal Joists", "Metal Fabrications", "Metal Gratings", "Metal Stairs"],
        "Wood, Plastics, and Composites": ["Framing Lumber", "Plywood", "Moldings", "Trim", "Custom Cabinets", "Wood Panels", "Composite Decking", "Plastic Lumber", "Wood Trusses", "Architectural Woodwork", "Structural Composite Lumber", "Exterior Finish Systems", "Plastic Trim"],
        "Thermal and Moisture Protection": ["Asphalt Shingles", "Metal Roofing", "Batt Insulation", "Spray Foam", "Membranes", "Sealants", "Intumescent Paint", "Fireproofing Boards", "Roofing Underlayment", "Vapor Barriers", "Waterproofing Membranes", "Exterior Insulation and Finish Systems (EIFS)", "Roof Hatches"],
        "Openings": ["Wood Doors", "Metal Doors", "Double Glazed Windows", "Skylights", "Hinges", "Locks", "Exterior Louvers", "Interior Louvers", "Overhead Doors", "Revolving Doors", "Door Frames", "Window Frames", "Door Hardware"],
        "Finishes": ["Standard Drywall", "Fire-Resistant Drywall", "Acoustic Ceiling Tiles", "Suspended Ceilings", "Vinyl", "Hardwood", "Paint", "Wall Panels", "Carpet", "Ceramic Tile", "Terrazzo", "Wall Coverings", "Specialty Coatings"],
        "Specialties": ["ADA Signage", "Directional Signs", "Paper Towel Dispensers", "Hand Dryers", "Fire Extinguishers", "Fire Hose Cabinets", "Metal Lockers", "Plastic Lockers", "Toilet Partitions", "Wall and Corner Guards", "Fire Protection Specialties", "Storage Specialties", "Postal Specialties"],
        "Equipment": ["Refrigerators", "Ovens", "Industrial Ovens", "Dishwashers", "Hospital Beds", "Diagnostic Machines", "Gym Equipment", "Playground Structures", "Loading Dock Equipment", "Residential Appliances", "Commercial Laundry Equipment", "Medical and Laboratory Equipment", "Library Equipment"],
        "Furnishings": ["Office Desks", "Chairs", "Blinds", "Curtains", "Entry Mats", "Area Rugs", "Built-In Cabinets", "Shelving", "Window Shades", "Fixed Seating", "Movable Furniture", "Art and Accessories", "Interior Plants"],
        "Special Construction": ["Pools", "Filtration Systems", "Wood Paneling", "Glass Panels", "Kennel Fencing", "Controlled Environment Rooms", "Radiation Protection", "Pre-Engineered Structures", "Special Purpose Rooms"],
        "Conveying Equipment": ["Passenger Elevators", "Freight Elevators", "Indoor Escalators", "Outdoor Escalators", "Small Service Elevators", "Industrial Dumbwaiters", "Airport Moving Walkways", "Shopping Mall Walkways", "Wheelchair Lifts", "Material Lifts", "Stair Lifts", "Vertical Platform Lifts"],
        "Fire Suppression": ["Sprinkler Heads", "Piping", "Hose Connections", "Standpipe Valves", "ABC Fire Extinguishers", "CO2 Fire Extinguishers", "Jockey Pumps", "Diesel Fire Pumps", "Wet-Pipe Sprinkler Systems", "Dry-Pipe Sprinkler Systems", "Fire Suppression Foam", "Fire Alarm Systems", "Pre-Action Sprinkler Systems"],
        "Plumbing": ["PVC Pipes", "Copper Pipes", "Elbows", "Couplings", "Gate Valves", "Ball Valves", "Water Heaters", "Plumbing Fixtures", "Sump Pumps", "Booster Pumps", "Water Supply Piping", "Sanitary Waste Piping", "Drainage Systems"],
        "Heating, Ventilating, and Air Conditioning (HVAC)": ["Split Systems", "Window Units", "Gas Furnaces", "Electric Furnaces", "Air Source Heat Pumps", "Ground Source Heat Pumps", "Exhaust Fans", "Air Handling Units", "Flexible Ducts", "Sheet Metal Ducts", "Programmable Thermostats", "Smart Thermostats", "Air Distribution Devices"],
        "Integrated Automation": ["Centralized Control Software", "Sensors and Actuators", "Thermostats", "Dampers", "Dimmers", "Motion Sensors", "Access Control Panels", "Security Cameras", "Building Automation Systems", "Energy Management Systems", "Environmental Control Systems", "Lighting Control Systems", "Network Integration"],
        "Electrical": ["Electrical Wires", "Network Cables", "EMT Conduits", "Conduit Connectors", "Light Switches", "Electrical Outlets", "LED Fixtures", "Fluorescent Fixtures", "Miniature Circuit Breakers", "Residual Current Circuit Breakers", "Step-Up Transformers", "Step-Down Transformers", "Electrical Panels"],
        "Communications": ["Cat 6 Cables", "Fiber Optic Cables", "VoIP Phones", "PBX Systems", "Projectors", "Sound Systems", "Speakers", "Microphones", "Data Communication Equipment", "Audio-Visual Equipment", "Public Address Systems", "Intercom Systems", "Networking Hardware"],
        "Electronic Safety and Security": ["Smoke Detectors", "Fire Alarm Panels", "IP Cameras", "CCTV Cameras", "Keycard Readers", "Biometric Scanners", "Motion Sensors", "Door Contacts", "Access Control Systems", "Intrusion Detection Systems", "Fire Detection Systems", "Security Management Systems", "Surveillance Systems"],
        "Earthwork": ["Backhoes", "Bulldozers", "Gravel", "Sand", "Lime", "Geotextiles", "Silt Fences", "Erosion Control Blankets", "Excavation Equipment", "Trenching Equipment", "Earth Moving Equipment", "Soil Compaction Equipment", "Site Grading Equipment"],
        "Exterior Improvements": ["Plants", "Mulch", "Chain Link Fences", "Wooden Fences", "Asphalt", "Pavers", "Benches", "Trash Receptacles", "Landscaping Materials", "Fencing and Gates", "Paving Materials", "Site Furnishings", "Exterior Lighting"],
        "Utilities": ["Water Mains", "Hydrants", "Sewer Pipes", "Manholes", "Catch Basins", "Storm Drains", "Conduits", "Access Panels", "Utility Structures", "Water Distribution Systems", "Wastewater Collection Systems", "Stormwater Management Systems", "Utility Tunnels"],
        "Transportation": ["Traffic Signals", "Road Signs", "Parking Meters", "Barriers", "Asphalt", "Concrete", "Traffic Control Devices", "Parking Equipment", "Roadway Construction Materials", "Traffic Management Systems", "Pavement Marking Materials", "Toll Collection Systems", "Bridge Components"]
    }

    template_entry = {
        "quantity": "",
        "unit": "units",
        "leadTime": "",
        "neededOnsite": "",
        "manufacturingTime": "",
        "etaDelivery": "",
        "manufacturer": "",
        "fabrication": "Local",
        "deliveryLocation": "Construction Site",
        "trackingNumber": "",
        "notes": "",
        "total lead time analysis": "Late",
        "shipped": False,
        "delivered": False,
        "attachFile": ""
    }

    for division_name, items in divisions.items():
        entries = []
        for item in items:
            entry = template_entry.copy()
            entry["name"] = item
            entries.append(entry)
        
        try:
            update_division_entries(project_name, division_name, entries)
        except Exception as e:
            print(f"Failed to update division {division_name} with error: {e}")


def fetch_user_preferences(email):
    """Fetch the user's notification preference for late tasks."""
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT amountOfDaysLate FROM UserPreferences WHERE userEmail = ?", (email,))
    preference = cursor.fetchone()
    conn.close()
    return preference[0] if preference else None  # Returns None if no preference is set

def calculate_days_late(needed_on, delivered_on):
    date_format = "%Y-%m-%d"
    if not is_valid_date(needed_on) or not is_valid_date(delivered_on):
        return 0  # or handle as appropriate for your application

    needed_on_date = datetime.datetime.strptime(needed_on, date_format)
    delivered_on_date = datetime.datetime.strptime(delivered_on, date_format)
    delta = delivered_on_date - needed_on_date
    return delta.days

def is_valid_date(date_str):
    return bool(re.match(r'^\d{4}-\d{2}-\d{2}$', date_str))


def fetch_late_entries_for_user(email):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Fetch all projects
    cursor.execute("SELECT name, owner_emails, divisions_data FROM Project")
    projects = cursor.fetchall()

    late_entries = []

    for project_name, owner_email, divisions_data_json in projects:
        divisions_data = json.loads(divisions_data_json)

        for division_name, division_info in divisions_data.items():
            # Check if the user is either the owner or mentioned in the division
            if email == owner_email or email in division_info["allowed_emails"]:
                for entry in division_info["entries"]:
                    eta_delivery = entry.get("etaDelivery", "")
                    needed_on_site = entry.get("neededOnsite", "")

                    # Ensure both dates are available and valid
                    if eta_delivery and needed_on_site:
                        days_late = calculate_days_late(needed_on_site, eta_delivery)
                        if days_late > 0:
                            late_entries.append({
                                "projectName": project_name,
                                "divisionName": division_name,
                                "entryName": entry.get("name", "Unnamed"),
                                "daysLate": days_late
                            })

    conn.close()
    return late_entries


def get_gpt4_default_printout_summary(division_name, entries):
    sorted_entries = sorted(entries, key=lambda x: x.get('neededOnsite', ''))
    prompt = f"""
    Generate a table for the {division_name} division, sorted by needed on-site date (earliest to latest).
    Use this exact format, including only the data provided:

    | Name | Quantity | Unit | Lead Time | Needed On-Site | Manufacturing Time | ETA Delivery | Status | Manufacturer |
    |------|----------|------|-----------|----------------|--------------------|--------------| -------|--------------|
    | <name> | <quantity> | <unit> | <leadTime> | <neededOnsite> | <manufacturingTime> | <etaDelivery> | <status> | <manufacturer> |

    Calculate the status as 'Late' if ETA Delivery is after Needed On-Site, 'On Time' if before or on the same date, and 'Close' if within 3 days.
    After the table, list any key points or issues based solely on the data provided. Do not make up any information.

    Entries: {json.dumps(sorted_entries, indent=2)}
    """
    return generate_gpt4_response(prompt)

def get_gpt4_item_summary_report(division_name, entries):
    sorted_entries = sorted(entries, key=lambda x: x.get('neededOnsite', ''))
    prompt = f"""
    Create a detailed table for the {division_name} division, sorted by needed on-site date (earliest to latest).
    Use this exact format, including only the data provided:

    | Name | Quantity | Unit | Lead Time | Needed On-Site | Manufacturing Time | ETA Delivery | Status | Manufacturer | Fabrication | Delivery Location | Tracking Number | Notes |
    |------|----------|------|-----------|----------------|--------------------|--------------| -------|--------------|-------------|-------------------|-----------------|-------|
    | <name> | <quantity> | <unit> | <leadTime> | <neededOnsite> | <manufacturingTime> | <etaDelivery> | <status> | <manufacturer> | <fabrication> | <deliveryLocation> | <trackingNumber> | <notes> |

    Calculate the status as 'Late' if ETA Delivery is after Needed On-Site, 'On Time' if before or on the same date, and 'Close' if within 3 days.
    After the table, list 3-5 key observations or issues based solely on the data provided. Do not make up any information.

    Entries: {json.dumps(sorted_entries, indent=2)}
    """
    return generate_gpt4_response(prompt)

def get_gpt4_lead_time_analysis_report(division_name, entries):
    prompt = f"""
    Generate a lead time analysis report for the {division_name} division.
    Use this exact format, including only the data provided:

    | Name | Lead Time | Manufacturer |
    |------|-----------|--------------|
    | <name> | <leadTime> | <manufacturer> |

    Sort the table by lead time (longest to shortest).

    After the table, provide these bullet points based solely on the data:
    • Average lead time: <calculated value>
    • Minimum lead time: <value> (<item name>)
    • Maximum lead time: <value> (<item name>)
    • 2-3 key observations about lead time patterns or issues (only if evident from the data)

    Entries: {json.dumps(entries, indent=2)}
    """
    return generate_gpt4_response(prompt)

def get_gpt4_manufacturing_time_report(division_name, entries):
    sorted_entries = sorted(entries, key=lambda x: int(x.get('manufacturingTime', 0)), reverse=True)
    prompt = f"""
    Create a manufacturing time report for the {division_name} division.
    Use this exact format, including only the data provided:

    | Name | Manufacturing Time | Needed On-Site | Manufacturer |
    |------|--------------------| ---------------|--------------|
    | <name> | <manufacturingTime> | <neededOnsite> | <manufacturer> |

    Sort the table by manufacturing time (longest to shortest).

    After the table, list 3-5 key observations or issues related to manufacturing times, based solely on the data provided. Do not make up any information.

    Entries: {json.dumps(sorted_entries, indent=2)}
    """
    return generate_gpt4_response(prompt)

def get_gpt4_eta_delivery_report(division_name, entries):
    sorted_entries = sorted(entries, key=lambda x: x.get('etaDelivery', ''))
    current_date = datetime.datetime.now().date()
    prompt = f"""
    Generate an ETA delivery report for the {division_name} division.
    Use this exact format, including only the data provided:

    | Name | Quantity | Unit | Needed On-Site | ETA Delivery | Status | Manufacturer |
    |------|----------|------|----------------|--------------|--------|--------------|
    | <name> | <quantity> | <unit> | <neededOnsite> | <etaDelivery> | <status> | <manufacturer> |

    Sort the table by ETA Delivery Date (earliest to latest).
    Calculate the status as:
    - 'Critical' if ETA is 10 days or less from today ({current_date}) or if it's past the Needed On-Site date
    - 'Warning' if ETA is within 30 days from today
    - 'On Track' otherwise

    Mark items with 'Critical' status in red.

    After the table, list 3-5 key points highlighting critical or warning status items and their impact, based solely on the data provided. Do not make up any information.

    Entries: {json.dumps(sorted_entries, indent=2)}
    """
    return generate_gpt4_response(prompt)

def get_gpt4_prefabrication_time_report(division_name, entries):
    sorted_entries = sorted(entries, key=lambda x: int(x.get('prefabricationTime', 0)), reverse=True)
    prompt = f"""
    Create a prefabrication time report for the {division_name} division.
    Use this exact format, including only the data provided:

    | Name | Prefab Time | Needed On-Site | Shop Drawing Approval | Field Measurement | Prefab Start |
    |------|-------------|-----------------|----------------------|-------------------|---------------|
    | <name> | <prefabTime> | <neededOnsite> | <shopDrawingApproval> | <fieldMeasurement> | <prefabStart> |

    Sort the table by Prefabrication Time (longest to shortest).

    After the table, list 3-5 key observations or issues related to prefabrication schedules, based solely on the data provided. Do not make up any information.

    Entries: {json.dumps(sorted_entries, indent=2)}
    """
    return generate_gpt4_response(prompt)

def get_gpt4_milestone_report(division_name, entries, start_date, end_date):
    prompt = f"""
    Generate a milestone report for the {division_name} division from {start_date} to {end_date}.
    Use this exact format, including only the data provided:

    | Milestone | Planned Date | Actual Date | Status |
    |-----------|--------------|-------------|--------|
    | <name> | <plannedDate> | <actualDate> | <status> |

    Sort the table by Planned Date (earliest to latest).
    Calculate the status as:
    - 'Completed' if Actual Date is filled and not later than Planned Date
    - 'Delayed' if Actual Date is later than Planned Date
    - 'Pending' if Actual Date is empty

    After the table, list 3-5 key points summarizing milestone progress and issues within the specified date range, based solely on the data provided. Do not make up any information.

    Entries: {json.dumps(entries, indent=2)}
    """
    return generate_gpt4_response(prompt)
def generate_gpt4_response(prompt):
    response = openai.ChatCompletion.create(
        model="gpt-4-turbo",
        messages=[
            {"role": "system", "content": "You are an AI specialized in generating concise, tabular reports for construction projects."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=1000
    )
    return response.choices[0]['message']['content'].strip()
