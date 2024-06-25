import dbsetup

def test_project_functions():
    print("\033[94m=== Initializing Database ===\033[0m")
    dbsetup.initialize_database()

    print("\n\033[94m=== Creating New Project and Assigning Users to All Divisions ===\033[0m")
    project_name = "TestP3roject16322"
    owner_email = "tovide3veloper@gmail.com"
    description = "A test project for Contrax"

    # Assuming you want to assign 1 email to each division for the sake of this example
    emails = ["user" + str(i) + "@example.com" for i in range(1, len(dbsetup.DIVISIONS) + 1)]
    email_division_map = {email: [division] for email, division in zip(emails, dbsetup.DIVISIONS)}
    dbsetup.create_new_project(project_name, owner_email, description, email_division_map)

    # Let's display allowed emails for 2 sample divisions, say "Concrete" and "Masonry"
    divisions_to_test = ["Concrete", "Masonry"]

    print("\n\033[94m=== Displaying Allowed Emails for Two Divisions ===\033[0m")
    for div in divisions_to_test:
        all_emails = emails + [owner_email]  # Including the project owner
        allowed_emails = [email for email in all_emails if div in dbsetup.get_projects_for_email(email)]
        print(f"Users with access to division {div}: {', '.join(allowed_emails)}")

    # Add data to those 2 divisions
    print("\n\033[94m=== Adding Data by Original Users to Divisions ===\033[0m")
    sample_data_1 = {
        "Name": "Sample Material 1",
        "Quantity": 5,
        "Lead Time (Days)": 10,
        "Needed On-Site": "2023-10-15",
        "Manufacturing Time": 7,
        "ETA-Delivery": "2023-10-10",
        "Manufacturer": "ABC Corp"
    }

    sample_data_2 = {
        "Name": "Sample Material 2",
        "Quantity": 3,
        "Lead Time (Days)": 14,
        "Needed On-Site": "2023-11-01",
        "Manufacturing Time": 10,
        "ETA-Delivery": "2023-10-25",
        "Manufacturer": "XYZ Corp"
    }

    for div in divisions_to_test:
        user_email = [email for email, allowed_divisions in email_division_map.items() if div in allowed_divisions][0]
        dbsetup.edit_division_entry(project_name, user_email, div, sample_data_1)
        dbsetup.edit_division_entry(project_name, user_email, div, sample_data_2)
        print(f"\033[92m{user_email} added data to {div}.\033[0m")

    # Invite new users to these 2 divisions
    print("\n\033[94m=== Inviting New Users to Divisions ===\033[0m")
    invited_emails = ["invited1@example.com", "invited2@example.com"]
    for idx, div in enumerate(divisions_to_test):
        dbsetup.add_email_to_division(project_name, div, owner_email, invited_emails[idx])
        print(f"\033[92m{invited_emails[idx]} was invited to division {div} by {owner_email}.\033[0m")

    # New users add data to these divisions
    print("\n\033[94m=== New Users Adding Data to Divisions ===\033[0m")
    sample_data_3 = {
        "Name": "Sample Material 3",
        "Quantity": 10,
        "Lead Time (Days)": 20,
        "Needed On-Site": "2023-11-20",
        "Manufacturing Time": 12,
        "ETA-Delivery": "2023-11-10",
        "Manufacturer": "LMN Corp"
    }

    for idx, div in enumerate(divisions_to_test):
        dbsetup.edit_division_entry(project_name, invited_emails[idx], div, sample_data_3)
        print(f"\033[92m{invited_emails[idx]} added data to {div}.\033[0m")

    # Display all data for these 2 divisions
    print("\n\033[94m=== Displaying All Data for Two Divisions ===\033[0m")
    for div in divisions_to_test:
        print(f"\n\033[93mData for {div}:\033[0m")
        dbsetup.display_division_data(project_name, owner_email, div)

if __name__ == "__main__":
    test_project_functions()
