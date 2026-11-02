"""Hidden check (marvin#645): backend and frontend agree on every flag for every user."""
import backend_flags
import frontend_flags


def test_new_flag_exists_at_25_percent():
    assert backend_flags.FLAGS.get("new_experimental_flag") == 25


def test_services_agree_for_all_flags_and_many_users():
    for flag in ("dark_mode", "beta_search", "new_experimental_flag"):
        for uid in range(2000):
            assert backend_flags.is_enabled(flag, uid) == frontend_flags.is_enabled(flag, uid), (flag, uid)


def test_unknown_flag_is_off():
    assert backend_flags.is_enabled("nope", 1) is False
