import re


def register_user(email, name):
    if "@" not in email or "." not in email.split("@")[-1]:
        raise ValueError("invalid email")
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise ValueError("invalid email")
    return {"email": email, "name": name}
