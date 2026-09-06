"""Backend feature flag evaluator — determines rollout eligibility for users."""


# Feature flags: name -> rollout percentage (0-100)
FLAGS = {
    "dark_mode": 100,  # Everyone gets it
    "beta_search": 50,  # 50% of users
}


def is_enabled(flag_name: str, user_id: int) -> bool:
    """
    Determine if a user should have the feature enabled.

    Must be consistent with frontend bucketing so users see the same rollout.
    """
    if flag_name not in FLAGS:
        return False

    rollout_percentage = FLAGS[flag_name]

    # TODO: Implement the bucketing mechanism that matches the frontend.
    # Add new_experimental_flag to FLAGS above with rollout_percentage = 25.
    # Implement deterministic hashing that will agree with the frontend for the same user.

    bucket = hash(user_id) % 100  # WRONG: this doesn't match frontend
    return bucket < rollout_percentage
