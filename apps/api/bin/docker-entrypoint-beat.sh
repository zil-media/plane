#!/bin/bash
set -e

python manage.py wait_for_db
# Wait for migrations
python manage.py wait_for_migrations
# exec: celery becomes PID 1 and gets the SIGTERM of a deploy, so it shuts down warm (finishes
# the tasks it is running) instead of being SIGKILLed with them when bash ignores the signal.
exec celery -A plane beat -l info
