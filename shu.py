import sqlite3

# Connect to your database (or create it if it doesn't exist)
conn = sqlite3.connect('projects.db')

# Create a cursor object
cursor = conn.cursor()

# SQL statement to create the milestones table
create_table_sql = """
CREATE TABLE IF NOT EXISTS milestones (
    id INTEGER PRIMARY KEY,
    project_name TEXT NOT NULL,
    division_name TEXT NOT NULL,
    description TEXT NOT NULL,
    completed BOOLEAN NOT NULL DEFAULT 0
);
"""

# Execute the SQL statement
cursor.execute(create_table_sql)

# Commit the changes and close the connection
conn.commit()
conn.close()

print("Table created successfully.")
