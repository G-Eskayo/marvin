"""Frontend feature flag evaluator — determines rollout eligibility for users."""
import hashlib

# Feature flags: name -> rollout percentage (0-100)
FLAGS = {
    "dark_mode": 100,  # Everyone gets it
    "beta_search": 50,  # 50% of users
    "new_experimental_flag": 25,  # 25% of users
}


def is_enabled(flag_name: str, user_id: int) -> bool:
    """
    Determine if a user should have the feature enabled.

    Uses consistent hashing: hash(flag_name:user_id) to bucket the user,
    ensuring the same user always gets the same experience.
    The bucket is consistent across restarts and across services.
    """
    if flag_name not in FLAGS:
        return False

    rollout_percentage = FLAGS[flag_name]

    # Create a deterministic hash of the flag + user combination
    digest = hashlib.sha256(f"{flag_name}:{user_id}".encode()).hexdigest()

    # Convert first 8 hex chars to a number in range [0, 100)
    bucket = int(digest[:8], 16) % 100

    return bucket < rollout_percentage
