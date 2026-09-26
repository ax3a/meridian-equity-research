"""`python -m meridian.worker` — the worker entrypoint used by the Docker service."""

from meridian.worker.service import main

if __name__ == "__main__":
    main()
