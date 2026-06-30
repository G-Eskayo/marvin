def add_user(db, name, email):
    """Add a new user. Raises ValueError if email already registered."""
    if email in [u['email'] for u in db if u.get('type') == 'user']:
        raise ValueError(f"Email {email} already exists")
    db.append({'type': 'user', 'name': name, 'email': email})
    return db


def add_order(db, user_email, item):
    """Add an order for an existing user. Raises ValueError if user not found."""
    if user_email not in [u['email'] for u in db if u.get('type') == 'user']:
        raise ValueError(f"User {user_email} not found")
    db.append({'type': 'order', 'user': user_email, 'item': item})
    return db
