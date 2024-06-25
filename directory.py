import sqlite3
import dbsetup

DB_NAME = 'projects.db'

def create_directory_table():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS directory_entries (
            directory_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT NOT NULL,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            email TEXT NOT NULL,
            company TEXT NOT NULL,
            phone_number TEXT,
            role TEXT NOT NULL,
            division TEXT NOT NULL,
            project_id INTEGER NOT NULL,
            FOREIGN KEY (project_id) REFERENCES Project(id)
        );
    ''')

    conn.commit()
    conn.close()

def get_user_directory(project_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Fetch the user's contacts with pagination
    cursor.execute('''
        SELECT first_name, last_name, email, phone_number, company, role, division
        FROM directory_entries
        WHERE project_id = ?
    ''', (project_id,))
# STOPPED HERE
    user_directory = cursor.fetchall()
    conn.close()

    keys = ['first_name', 'last_name', 'email', 'phone_number', 'company', 'role', 'division']

    directory_list = [dict(zip(keys, contact)) for contact in user_directory]

    unique_directory_list = []
    seen = set()

    for contact in directory_list:
        # Create a unique key for each contact based on its details
        unique_key = (contact['first_name'], contact['last_name'], contact['email'], contact['phone_number'], contact['company'], contact['role'], contact['division'])
        if unique_key not in seen:
            seen.add(unique_key)
            unique_directory_list.append(contact)

    sorted_dir_list = sorted(unique_directory_list, key=lambda x: x['company'])

    return sorted_dir_list

def add_to_user_directory(user_email, first_name, last_name, email, company, phone, role, division, project_id):
    # user_email is the ADDER's email for auditing purposes
    # added_user should have at minimum email and Company name
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Check for duplicates
    cursor.execute('SELECT * FROM directory_entries WHERE email = ? AND project_id = ?', (email, project_id))
    duplicate = cursor.fetchone()

    if duplicate:
        conn.close()
        return {'success': False, 'error': 'Entry already exists'}

    cursor.execute('INSERT INTO directory_entries (user_email, first_name, last_name, email, company, phone_number, role, division, project_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', (user_email, first_name, last_name, email, company, phone, role, division, project_id))

    cursor.execute('SELECT name FROM Project WHERE id = ?', (project_id,))
    res = cursor.fetchone()

    conn.commit()
    conn.close()

    emailData = [{
        'email': email,
        'role': role, 
        'company': company,
    }]

    # invite user to the project
    success = dbsetup.add_emails_to_division(res[0], division, emailData)

    return success

# ATTENTION: 
if __name__ == '__main__':
    create_directory_table()

# add_to_user_directory('hortonchristopher27@gmail.com', 'Christopher', 'Horton', 'christopher.horton@caci.com' , 'CACI', '703-123-4567', 'Supplier', 'Concrete', 70 ) if 