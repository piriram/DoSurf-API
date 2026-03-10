"""Backward-compatible entrypoint for collection job."""

from app.services.collection import main, run_collection

__all__ = ["main", "run_collection"]


if __name__ == "__main__":
    main()
