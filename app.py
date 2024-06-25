from flask import Flask, redirect, url_for, session, render_template, request, jsonify, send_file
from flask_oauthlib.client import OAuth
import dbsetup  # Your db setup
import directory
import jwt
import requests
import easypost
import re
from datetime import datetime
import sqlite3
from functools import wraps
import os
import uuid
import json

app = Flask(__name__)
app.config['DEBUG'] = True
app.secret_key = 'your_secret_key_here'
easypost.api_key = "EZAKf97c337f35824e59bf9f5b0eef6a7d46j2O2eTpWuemZRCy6q0R30A"
oauth = OAuth(app)

auth0 = oauth.remote_app(
    'auth0',
    consumer_key='hONEVh1Tf4WCdjow5flwai7KVobiETAP',
    consumer_secret='iakh8Pk631Y_p5mq1FracSacfKFGNbcfx2wE6H7ND6C1Dz7BlBGqSeVyXFo9QWwy',
    request_token_params={
        'scope': 'openid profile email',
    },
    base_url='https://dev-gizpjh8y3uetudi1.us.auth0.com/v2/',
    access_token_method='POST',
    access_token_url='https://dev-gizpjh8y3uetudi1.us.auth0.com/v2/oauth/token',
    authorize_url='https://dev-gizpjh8y3uetudi1.us.auth0.com/v2/authorize',
)


@auth0.tokengetter
def get_auth0_oauth_token():
    return session.get('token')

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'email' not in session:
            return redirect('/')
        return f(*args, **kwargs)
    return decorated

def log_action(user_email, action):
    with open('log.txt', 'a') as log_file:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"{timestamp} - {user_email} - {action}\n"
        log_file.write(log_entry)

def is_valid_tracking_number(tracking_number):
    """
    Basic validation for tracking numbers. This is a simplistic check.
    Real validation logic might depend on specific carrier formats.
    """
    # Example: Basic check for length and alphanumeric status
    # Note: Real tracking numbers have more complex rules that can vary by carrier
    return bool(re.match(r'^[A-Za-z0-9]{10,30}$', tracking_number))

@app.route('/uploadNoteFiles/<string:project_name>/<string:division_name>/data', methods=['POST'])
def upload_file(project_name, division_name):
    try:
        uploaded_data = {}
        for key in request.form:
            if key.startswith('row'):
                row_data = request.form[key]
                row_data = json.loads(row_data)
                uploaded_data[key] = row_data['row']
        i = 0
        for key in request.files:
            if key.startswith('file'):
                file = request.files[key]
                # get the file extension
                file_extension = file.filename.split('.')[-1]
                # create a unique id for the filename
                id = uuid.uuid4()
                UPLOAD_PATH = "./upload"
                filepath = os.path.join(UPLOAD_PATH, str(id) + '.' + file_extension)
                file.save(filepath)
                rowData = uploaded_data['row' + str(i)]
                rowData['file'] = filepath
                # uses side affects to update the database
                dbsetup.edit_division_entry(project_name, session.get('email'), division_name, rowData)
                i += 1
                return jsonify({'success': True, 'message': 'File uploaded successfully'})
            else:
                return jsonify({'success': False, 'message': 'No file uploaded'}), 400

    except Exception as e:
        print("There was an error: ", e)
        return jsonify({"error": str(e)}), 500

@app.route('/downloadNoteFile', methods=['POST'])
def download_file():
    data = request.get_json()
    file_path = data.get('filePath')
    try:
        return send_file(file_path, as_attachment=True)
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/track-shipment', methods=['POST'])
@requires_auth
def track_shipment():
    data = request.get_json()

    # Validate the request data
    try:
        tracking_number = data.get('tracking_number')
        carrier = data.get('carrier').upper()  # USPS or UPS
    except AttributeError:
        return jsonify({'error': 'Invalid request data.'}), 400

    if not is_valid_tracking_number(tracking_number):
        return jsonify({'error': 'Invalid tracking number format.'}), 400

    try:
        tracker = easypost.Tracker.create(
            carrier=carrier,
            tracking_code=tracking_number,
        )
        return jsonify(tracker), 200
    except Exception as e:
        # Handle errors (e.g., network issues, invalid API key, unsupported carrier)
        return jsonify({'error': str(e)}), 500


@app.route('/')
def home():
    # if a session is active, just redirect to dashboard
    if 'email' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')
@app.route('/generate-report/<project_name>/<report_type>')
@requires_auth
def generate_report(project_name, report_type):
    project_data, error = dbsetup.fetch_project_data_for_pdf(project_name)

    if error:
        return jsonify({'error': error}), 404

    # Get date range for milestone report
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    # Choose the appropriate report function based on the report_type
    report_functions = {
        'default': dbsetup.get_gpt4_default_printout_summary,
        'item_summary': dbsetup.get_gpt4_item_summary_report,
        'lead_time_analysis': dbsetup.get_gpt4_lead_time_analysis_report,
        'manufacturing_time': dbsetup.get_gpt4_manufacturing_time_report,
        'eta_delivery': dbsetup.get_gpt4_eta_delivery_report,
        'prefabrication_time': dbsetup.get_gpt4_prefabrication_time_report,
        'milestone': lambda division_name, entries: dbsetup.get_gpt4_milestone_report(division_name, entries, start_date, end_date)
    }

    if report_type not in report_functions:
        return jsonify({'error': 'Invalid report type'}), 400

    generate_report_function = report_functions[report_type]
    
    # Generate and return the PDF response
    return dbsetup.generate_pdf_with_gpt4(project_data, f"{project_name}_{report_type}_report.pdf", generate_report_function)
@app.route('/login')
def login():
    return auth0.authorize(callback=url_for('callback', _external=True))

@app.route('/delete-division/<string:project_name>/<string:division_name>', methods=['DELETE'])
@requires_auth
def delete_division(project_name, division_name):
    try:
        # Assuming a function exists to delete the division
        success = dbsetup.delete_division(project_name, division_name)

        if success:
            user_email = session.get('email')
            log_action(user_email,f"deleted division {division_name} on project {project_name}")
            return jsonify({'success': True, 'message': 'Division deleted successfully'})

        else:
            return jsonify({'success': False, 'message': 'Failed to delete division'})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/add-division/<string:project_name>', methods=['POST'])
@requires_auth
def add_division(project_name):
    try:
        data = request.get_json()
        division_name = data.get('divisionName')
        user_email = session.get('email')
        if dbsetup.add_new_division(project_name, division_name, user_email):
            log_action(user_email,f"generated a new division on {project_name}")
            return jsonify({'success': True, 'message': 'Division added successfully'})
        else:
            return jsonify({'success': False, 'message': 'Failed to add division'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/add-note/<string:project_name>/<string:division_name>', methods=['POST'])
@requires_auth
def add_note_to_division(project_name, division_name):
    try:
        data = request.get_json()
        user_email = session.get('email')
        note = data.get('note')
        dbsetup.add_note_to_division(project_name, division_name, user_email, note)
        log_action(user_email,f"added a note to {division_name} on project {project_name}")
        return jsonify({'success': True, 'message': 'Note added successfully'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route("/callback")
def callback():

    # Get the code from the callback
    code = request.args.get('code')
    if not code:
        return jsonify(error="Authorization code missing"), 400

    # Exchange the code for tokens
    token_payload = {
        "client_id": auth0.consumer_key,
        "client_secret": auth0.consumer_secret,
        "code": code,
        "grant_type": "authorization_code",
        #"redirect_uri": "http://127.0.0.1:5000/dashboard",
         "redirect_uri": "http://contrax.co/dashboard" ##### CHANGE TO CONTRAX.CO
    }
    token_response = requests.post(auth0.access_token_url, data=token_payload)
    print(token_response.json())
    token_json = token_response.json()

    # Get the ID token from the response
    id_token = token_json.get('id_token')
    if not id_token:
        return jsonify(error="ID token missing from token endpoint response"), 400

    decoded_jwt = jwt.decode(id_token, options={"verify_signature": False}, algorithms=['RS256'])

        # Extract user email
    user_email = decoded_jwt['email']

        # Save the email in the session
    session['email'] = user_email
    log_action(user_email,f"logged in")
        # Redirect the user to the dashboard
    return redirect(url_for('dashboard'))

@app.route('/dashboard')
@requires_auth
def dashboard():
    # Check if the user's email is in the session
    user_email = session.get('email')  # This should be set after the user logs in
    if not user_email:
        return redirect(url_for('login'))
    # Use the email to fetch projects and their associated divisions for this user
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
    projects_info = dbsetup.get_projects_for_email(user_email)
    roles = dbsetup.get_roles()
    return render_template('dashboard.html', user_email=user_email, projects_info=projects_info, DIVISIONS=DIVISIONS, ROLES=roles)

@app.route('/create-project', methods=['POST'])
def create_project():
    try:
        data = request.get_json()
        project_name = data.get('projectName')
        project_description = data.get('projectDescription')
        email_division_map = data.get('emailDivisionMap', {})
        custom_divisions = data.get('customDivisions', {})
        user_email = session.get('email')

        if not project_name or not project_description:
            return jsonify({'success': False, 'error': 'Project name and description are required.'}), 400

        # Call the function to create a new project
        dbsetup.create_new_project(project_name, user_email, project_description, custom_divisions, email_division_map)
        dbsetup.default_data_addition(project_name)
        log_action(user_email, f"generated a new project {project_name}")
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/logout')
@requires_auth
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.route('/project/<int:project_id>/division/<division_name>', methods=['GET'])
@requires_auth
def get_division_data(project_id, division_name):
    try:
        user_email = session.get('email')
        if not user_email:
            return jsonify({'success': False, 'error': 'User not logged in.'}), 401

        # Get division data from the helper function
        log_action(user_email,f"looked at division: {division_name} in {project_id}")
        division_data = dbsetup.db_get_division_data(project_id, division_name, user_email)

        return jsonify({'success': True, 'data': division_data})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500



@app.route('/get-divisions-by-project-name/<project_name>', methods=['GET'])
@requires_auth
def get_divisions_by_project_name_route(project_name):
    user_email = session.get('email')
    if not user_email:
        return jsonify({'success': False, 'error': 'User not logged in.'}), 401

    try:
        result = dbsetup.get_divisions_for_project(project_name,user_email)
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/view-divisions')
@requires_auth
def view_divisions():
    project_name = request.args.get('projectName')
    requester_email = session.get('email')
    # refactor here probably want to use project_id instead
    project_info = dbsetup.get_project_info(project_name)

    if not project_info['success']:
        return 'Error: ' + project_info['error'], 404

    is_owner = requester_email == project_info['owner_email']

    users = []
    project_id = dbsetup.get_project_id(project_name, requester_email)

    if is_owner:
        # grab some data for directory feature
        users = directory.get_user_directory(project_id)

    return render_template('view_divisions.html', project_id=project_id, project_name=project_name, is_owner=is_owner, divisions=project_info['divisions'], user_email=requester_email, users=users)

@app.route('/delete-project/<string:project_name>', methods=['POST'])
@requires_auth
def delete_project(project_name):
    requester_email = session.get('email')
    project_info = dbsetup.get_project_info(project_name)
    if requester_email != project_info['owner_email']:
        return jsonify({'success': False, 'message': 'Only the project owner can delete the project'}), 403

    if dbsetup.delete_project(project_name):
        log_action(requester_email, f"deleted project {project_name}")
        return jsonify({'success': True, 'message': 'Project deleted successfully'})
    else:
        return jsonify({'success': False, 'message': 'Failed to delete project'})

@app.route('/division-data/<project_name>/<division_name>')
@requires_auth
def division_data(project_name, division_name):
    email = session.get('email')
    entries, error = dbsetup.fetch_division_data(project_name, division_name, email)

    if error:
        print(error)  # Or log the error as needed
        return jsonify({'success': False, 'error': str(error)}), 500

    return jsonify({'success': True, 'entries': entries})

@app.route('/view-division/<project_name>/<division_name>')
@requires_auth
def view_division(project_name, division_name):
    # You can include additional context if necessary
    role = dbsetup.get_role(session.get('email'), project_name, division_name)
    authorized_emails = dbsetup.get_emails_for_division(project_name, division_name)
    all_roles = dbsetup.get_roles()
    return render_template('divisions_data.html', project_name=project_name, division_name=division_name, user_email=session.get('email'), role=role, authorized_emails=authorized_emails, roles=all_roles)


@app.route('/update-division1/<string:projectName>/<string:divisionName>/data', methods=['POST'])
@requires_auth
def update_division_data2(projectName, divisionName):
    try:
        # Extract the project name and division name from the URL
        project_name = projectName
        editor_email = session.get('email')  # Replace with the actual editor's email
        target_division = divisionName

        # Get the submitted data from the request
        submitted_data = request.json

        # Ensure the submitted data is a list of dictionaries

        if not isinstance(submitted_data, list) or not all(isinstance(item, dict) for item in submitted_data):
            return jsonify({"message": "Invalid data format. Expected a list of dictionaries."}), 400

        # Iterate through the submitted data and update each entry
        for update_data in submitted_data:
            success = dbsetup.edit_division_entry(project_name, editor_email, target_division, update_data)
            if not success:
                return jsonify({"message": "Failed to update entry."}), 400
        log_action(editor_email,f"editted division {divisionName} on project {projectName}")
        return jsonify({"message": "Data updated successfully."}), 200

    except Exception as e:
        return jsonify({"message": str(e)}), 500

@app.route('/invite-to-division/<string:project_name>/<string:division_name>', methods=['POST'])
@requires_auth
def invite_to_division(project_name, division_name):
    try:
        data = request.json
        user_email = session.get('email')

        # Attempt to add new emails to the division
        success = dbsetup.add_emails_to_division(project_name, division_name, data)

        if success:
            # Send an email to each newly invited user
            for email in data:
                subject = f"Invitation to join division: {division_name}"
                body = f"You have been invited to join the '{division_name}' division in the '{project_name}' project. https://contrax.co/view-division/{project_name}/{division_name}"
                dbsetup.send_email(email['email'], subject, body)  # Utilize your send_email function
            log_action(user_email,f"invited {email['email']} to {project_name}")
            return jsonify({'success': True, 'message': 'Emails added successfully'})
        else:
            return jsonify({'success': False, 'message': 'Failed to add emails'})

    except Exception as e:
        # If there's an error, return the error message
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/update-division/<string:project_name>/<string:division_name>/data', methods=['POST'])
@requires_auth
def update_division_data(project_name, division_name):
    try:
        data = request.get_json()  
        print(data)# Get JSON data from the request
        
        # arrays of names of changed columns
        for key in data:
            for item in data[key]:
                success = dbsetup.send_status_notification(project_name, division_name, item["shippedNotification"], item["deliveredNotification"])
                break

        # Call the function to update the database
        dbsetup.update_division_entries(project_name, division_name, data)
        return jsonify({'success': True, 'message': 'Data updated successfully'})
    except Exception as e:
        # Log the exception
        print(f"An error occurred: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

################################################################

@app.route('/settings', methods=['GET', 'POST'])
@requires_auth
def settings():
    user_email = session.get('email')
    if not user_email:
        return redirect(url_for('login'))

    if request.method == 'POST':
        # Update settings
        amount_of_days_late = request.form.get('amountOfDaysLate')
        update_user_settings(user_email, amount_of_days_late)
        return redirect(url_for('settings'))
    else:
        # Get current settings
        current_setting = get_user_settings(user_email)
        return render_template('settings.html', email=user_email, current_setting=current_setting)

def get_user_settings(user_email):
    conn = sqlite3.connect('users.db')
    cur = conn.cursor()
    cur.execute("SELECT amountOfDaysLate FROM user_settings WHERE userEmail = ?", (user_email,))
    result = cur.fetchone()
    conn.close()
    if result:
        return result[0]
    else:
        return None

@app.route('/late-tasks')
@requires_auth
def get_late_tasks():
    user_email = session.get('email')  # Make sure you're retrieving the correct session key for the user's email
    if not user_email:
        return jsonify({'error': 'User not authenticated'}), 403

    late_entries = dbsetup.fetch_late_entries_for_user(user_email)

    # Prepare the response to match what the frontend expects
    response = {
        'success': True,
        'lateTasks': late_entries if late_entries else []
    }

    print(response)
    return jsonify(response)

def update_user_settings(user_email, amount_of_days_late):
    conn = sqlite3.connect('users.db')
    cur = conn.cursor()
    # Update or insert new setting
    cur.execute("INSERT OR REPLACE INTO user_settings (userEmail, amountOfDaysLate) VALUES (?, ?)", (user_email, amount_of_days_late))
    conn.commit()
    conn.close()

@app.route('/add-milestone', methods=['POST'])
@requires_auth
def add_milestone():
    if request.method == 'POST':
        data = request.json
        project_name = data.get('project_name')
        division_name = data.get('division_name')
        description = data.get('description')

        conn = sqlite3.connect('projects.db')
        cursor = conn.cursor()
        cursor.execute('INSERT INTO milestones (project_name, division_name, description, completed) VALUES (?, ?, ?, ?)',
                       (project_name, division_name, description, 0))
        conn.commit()
        conn.close()

        return jsonify({'success': True})

@app.route('/toggle-milestone', methods=['POST'])
@requires_auth
def toggle_milestone():
    if request.method == 'POST':
        data = request.json
        milestone_id = data.get('milestoneId')
        completed = data.get('completed')

        conn = sqlite3.connect('projects.db')
        cursor = conn.cursor()
        cursor.execute('UPDATE milestones SET completed = ? WHERE id = ?', (completed, milestone_id))
        conn.commit()
        conn.close()

        return jsonify({'success': True})

@app.route('/remove-milestone', methods=['POST'])
@requires_auth
def remove_milestone():
    if request.method == 'POST':
        data = request.json
        milestone_id = data.get('milestoneId')

        conn = sqlite3.connect('projects.db')
        cursor = conn.cursor()
        cursor.execute('DELETE FROM milestones WHERE id = ?', (milestone_id,))
        conn.commit()
        conn.close()

        return jsonify({'success': True})

@app.route('/get-milestones', methods=['GET'])
@requires_auth
def get_milestones():
    project_name = request.args.get('project_name')
    division_name = request.args.get('division_name')

    conn = sqlite3.connect('projects.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id, description, completed FROM milestones WHERE project_name = ? AND division_name = ?',
                   (project_name, division_name))
    milestones = cursor.fetchall()
    conn.close()

    return jsonify([{'id': id, 'description': description, 'completed': completed} for id, description, completed in milestones])

@app.route('/add-directory-entry', methods=['POST'])
@requires_auth
def add_directory_entry():
    data = request.json
    user_email = session.get('email')
    company_name = data.get('company')
    phone_number = data.get('phone')
    email = data.get('email')
    first_name = data.get('first_name')
    last_name = data.get('last_name')
    role = data.get('role')
    division = data.get('division')
    project_id = data.get('project_id')

    res = directory.add_to_user_directory(user_email, first_name=first_name, last_name=last_name,
                                    email=email, company=company_name, phone=phone_number, 
                                    role=role, division=division, project_id=project_id)
    
    if not res:
        return jsonify({'success': False, 'message': 'Failed to add directory entry'}), 500

    return jsonify({'success': True})

if __name__ == '__main__':
    app.run(debug=True)
