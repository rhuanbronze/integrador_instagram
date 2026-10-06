"""Apply migrations, then replace this process with one Uvicorn worker."""

import os
import sys

from alembic.config import Config

from alembic import command


def main() -> None:
    try:
        command.upgrade(Config("alembic.ini"), "head")
    except Exception:
        print("Startup migration failed; verify environment and database", file=sys.stderr)
        raise SystemExit(1) from None
    os.execvp(
        "uvicorn",
        ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"],
    )


if __name__ == "__main__":
    main()
