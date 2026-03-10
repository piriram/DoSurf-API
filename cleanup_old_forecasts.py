"""Backward-compatible cleanup entrypoint.

Real implementation moved to jobs/cleanup_old_forecasts.py.
"""

from jobs.cleanup_old_forecasts import *  # noqa: F401,F403


if __name__ == "__main__":
    from jobs.cleanup_old_forecasts import main

    main()
