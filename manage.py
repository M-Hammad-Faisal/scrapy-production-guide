#!/usr/bin/env python
"""Django entry point for the manual-entry API:

    MANUAL_ENTRY_KEYS="alice:s3cret" python manage.py runserver 8000
"""

import os
import sys

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "manual_entry.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
