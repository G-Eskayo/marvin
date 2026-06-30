import re


def create_order(customer_email, items):
    if "@" not in customer_email or "." not in customer_email.split("@")[-1]:
        raise ValueError("invalid email")
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", customer_email):
        raise ValueError("invalid email")
    return {"email": customer_email, "items": items}
