#!/usr/bin/env python3
import re
import sys
from datetime import datetime, timedelta
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import LOG_RETENTION_DAYS, LOG_FILE


def clean_old_logs(log_file_path, days_to_keep=LOG_RETENTION_DAYS):
    current_date = datetime.now()
    cutoff_date = current_date - timedelta(days=days_to_keep)

    with open(log_file_path, "r") as file:
        lines = file.readlines()

    # Keep only lines newer than the cutoff date
    new_lines = []
    for line in lines:
        match = re.match(r"(\d{4}-\d{2}-\d{2})", line)
        if match:
            log_date = datetime.strptime(match.group(1), "%Y-%m-%d")
            if log_date >= cutoff_date:
                new_lines.append(line)

    temp_file = log_file_path + ".tmp"
    with open(temp_file, "w") as file:
        file.writelines(new_lines)

    os.replace(temp_file, log_file_path)

    removed_lines = len(lines) - len(new_lines)
    print(f"Removed {removed_lines} lines older than {days_to_keep} days")
    print(f"Remaining lines: {len(new_lines)}")


if __name__ == "__main__":
    if not os.path.exists(LOG_FILE):
        print(f"Error: file {LOG_FILE} not found")
        exit(1)

    clean_old_logs(LOG_FILE)
