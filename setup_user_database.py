import sqlite3

def create_database():
    # Connect to SQLite database (or create it if it doesn't exist)
    conn = sqlite3.connect('users.db')
    
    # Create a cursor object using the cursor() method
    cursor = conn.cursor()
    
    # Create table as per requirement
    sql = '''CREATE TABLE IF NOT EXISTS user_settings (
                userEmail TEXT PRIMARY KEY,
                amountOfDaysLate INTEGER
            );'''
    
    # Execute the SQL statement
    cursor.execute(sql)
    
    # Commit the changes
    conn.commit()
    
    # Close the database connection
    conn.close()
    
    print("Database and table created successfully.")

# Call the function to create the database and table
create_database()
