The team is rolling out a new feature flag `new_experimental_flag` on both frontend and backend services.

**What needs to be done:**

Add a new flag to `backend_flags.py` named `new_experimental_flag` that determines whether a given user should have this feature enabled. 

The implementation should follow the same bucketing mechanism used elsewhere in this codebase. A user should see the feature on both frontend and backend if and only if they are "bucketed in" — meaning they hash into the rollout percentage for that flag.

The frontend service already has this flag implemented in `frontend_flags.py`. The two services must agree on which users are bucketed in, or your rollout will show inconsistent behavior in production.

Update `backend_flags.py` and any other necessary files to add this flag correctly.
