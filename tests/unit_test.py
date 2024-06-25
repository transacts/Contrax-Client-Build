import dbsetup as pdb

# Function to add colors to printed text for clarity
def print_colored(text, color_code):
    """
    Available color codes:
    - RED: 91
    - GREEN: 92
    - YELLOW: 93
    - BLUE: 94
    """
    print(f"\033[{color_code}m{text}\033[0m")


def main():
    # Create the initial database structure
    pdb.initialize_database()
    
    # Create a new project "contrax-test-1" with a unique email in each division
    email_division_map = {}
    for i, division in enumerate(pdb.DIVISIONS):
        email_division_map[f"user{i}@test.com"] = [division]

    print_colored("Creating new project: contrax-test-5", 994)
    #pdb.create_new_project("contrax-test-4", "aundreas@themanagingcontracotrguy.com", "This is a test project!", email_division_map)

    # Have some of these emails add new users to their respective divisions
    additions = [
        ("user0@test.com", "new_user1@test.com"),
        ("user1@test.com", "new_user2@test.com"),
        ("user2@test.com", "new_user3@test.com"),
        ("user3@test.com", "new_user4@test.com"),
        ("user4@test.com", "new_user5@test.com"),
    ]

    for adding_email, new_email in additions:
        division_of_adding_email = pdb.get_divisions_for_email("contrax-test-4", adding_email)
        if division_of_adding_email:
            division = division_of_adding_email[0]
            print_colored(f"{adding_email} (from {division} division) is attempting to add {new_email} to {division}.", 93)
            pdb.add_email_to_division("contrax-test-4", division, adding_email, new_email)

    # Check permissions of each user
    all_emails = [email for email in email_division_map.keys()] + [new_email for _, new_email in additions]

    for email in all_emails:
        divisions = pdb.get_divisions_for_email("contrax-test-4", email)
        divisions_str = ', '.join(divisions)
        print_colored(f"{email} has access to: {divisions_str}", 92)


if __name__ == '__main__':
    main()
