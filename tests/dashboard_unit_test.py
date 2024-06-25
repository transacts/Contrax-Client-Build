import dbsetup as pdb
import random

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
    
    # Create a new project with "josh.geyfman@gmail.com"
    email_division_map = {
        "josh.geyfman@gmail.com": pdb.DIVISIONS
    }

    print_colored("Creating new project: contrax-test-1 with owner josh.geyfman@gmail.com", 94)
    pdb.create_new_project("contrax-test-1", "josh.geyfman@gmail.com", "Josh's first test project!", email_division_map)

    # Create a new project with a random owner and add "josh.geyfman@gmail.com" to two divisions
    random_email = f"owner{random.randint(1000,9999)}@random.com"
    email_division_map = {
        random_email: pdb.DIVISIONS,
        "josh.geyfman@gmail.com": [pdb.DIVISIONS[1], pdb.DIVISIONS[3]]  # Adding to 2nd and 4th division
    }

    print_colored(f"Creating new project: contrax-test-2 with random owner {random_email}", 94)
    pdb.create_new_project("contrax-test-2", random_email, "Second test project with random owner!", email_division_map)

    # Create a third project with another random owner and add "josh.geyfman@gmail.com" to a different division
    another_random_email = f"owner{random.randint(1000,9999)}@another.com"
    email_division_map = {
        another_random_email: pdb.DIVISIONS,
        "josh.geyfman@gmail.com": [pdb.DIVISIONS[2]]  # Adding to 3rd division
    }

    print_colored(f"Creating new project: contrax-test-3 with another random owner {another_random_email}", 94)
    pdb.create_new_project("contrax-test-3", another_random_email, "Third test project with another random owner!", email_division_map)

    # Check permissions of Josh Geyfman across all projects
    projects = ["contrax-test-1", "contrax-test-2", "contrax-test-3"]
    for project in projects:
        divisions = pdb.get_divisions_for_email(project, "josh.geyfman@gmail.com")
        divisions_str = ', '.join(divisions) if divisions else "No access"
        print_colored(f"Josh Geyfman has access to {divisions_str} in project {project}", 92)

if __name__ == '__main__':
    main()
