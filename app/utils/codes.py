import secrets
import string

def generate_org_code(length=6):
    chars = string.ascii_uppercase + string.digits
    return f"ORG-{''.join(secrets.choice(chars) for _ in range(length))}"

def generate_random_password(length=12):
    # Generates a secure string with letters and digits
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))