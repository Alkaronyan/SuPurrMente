#!/bin/sh
set -e

# Pass any arguments through directly (e.g. python src/migrate.py)
if [ "$#" -gt 0 ]; then
    exec "$@"
fi

# Default: run as cron daemon
# Logs are forwarded to container stdout via /proc/1/fd/1
CRON_SCHEDULE=$(python -c "import yaml; print(yaml.safe_load(open('/app/config.yml'))['schedule']['cron'])")

# cron runs with a minimal PATH (/usr/bin:/bin) that excludes /usr/local/bin where
# python lives in the slim image — so the job needs PATH and credentials injected
# explicitly. Forward the container env into the crontab; without this the hourly
# job dies with "python: not found".
{
    echo "PATH=$PATH"
    # Whisker/Gmail secrets come from the container env (env_file in compose). cron
    # does not inherit them, so persist them into the crontab environment.
    for var in WHISKER_USERNAME WHISKER_PASSWORD GMAIL_APP_PASSWORD FROM_EMAIL TO_EMAILS; do
        eval "val=\${$var}"
        [ -n "$val" ] && echo "$var=$val"
    done
    echo "$CRON_SCHEDULE cd /app && python src/main.py >> /proc/1/fd/1 2>&1"
} | crontab -

exec cron -f
