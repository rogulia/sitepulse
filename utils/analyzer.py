import os
import sys
import re
from collections import defaultdict
from statistics import mean, stdev
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configuration
DAYS_TO_ANALYZE = 7  # Number of days to analyze
PAGES_TO_SHOW = 10


def parse_logs(log_file_path, days_limit=DAYS_TO_ANALYZE):
    load_times = defaultdict(list)
    status_codes = defaultdict(lambda: defaultdict(int))
    errors = defaultdict(list)
    warnings = defaultdict(list)
    response_sizes = defaultdict(list)
    device_stats = defaultdict(lambda: defaultdict(int))

    with open(log_file_path, "r") as file:
        for line in file:
            try:
                log_date = datetime.strptime(line.split()[0], "%Y-%m-%d")
                if days_limit and (datetime.now() - log_date).days > days_limit:
                    continue
            except (ValueError, IndexError):
                continue

            if "Checked" in line:
                parse_check_line(
                    line, load_times, status_codes, response_sizes, device_stats
                )
            elif "ERROR" in line:
                parse_error_line(line, errors)
            elif "WARNING" in line:
                parse_warning_line(line, warnings)

    return load_times, status_codes, errors, warnings, response_sizes, device_stats


def parse_check_line(line, load_times, status_codes, response_sizes, device_stats):
    pattern = (
        r"Checked (\w+) (https://[^\s]+) - status (\d+), size (\d+), time ([\d.]+) sec"
    )
    match = re.search(pattern, line)
    if match:
        device, url, status, size, time = match.groups()
        load_times[url].append(float(time))
        status_codes[url][status] += 1
        response_sizes[url].append(int(size))
        device_stats[url][device] += 1


def parse_error_line(line, errors):
    pattern = r"ERROR.*?(https://[^\s]+) - (.+)"
    match = re.search(pattern, line)
    if match:
        url, error = match.groups()
        errors[url].append(error)


def parse_warning_line(line, warnings):
    pattern = r"WARNING.*?(https://[^\s]+) - (.+)"
    match = re.search(pattern, line)
    if match:
        url, warning = match.groups()
        warnings[url].append(warning)


def get_slowest_pages(load_times):
    # Group URLs by base path, ignoring locale prefixes
    grouped_times = defaultdict(list)
    for url, times in load_times.items():
        if "/faq/" in url:
            continue
        base_url = re.sub(r"/[a-z]{2}/", "/", url)
        grouped_times[base_url].extend(times)

    avg_times = [
        (base_url, mean(times), max(times), min(times))
        for base_url, times in grouped_times.items()
    ]
    return sorted(avg_times, key=lambda x: x[1], reverse=True)[:PAGES_TO_SHOW]


def get_most_unstable_pages(load_times):
    # Group URLs by base path, ignoring locale prefixes
    grouped_times = defaultdict(list)
    for url, times in load_times.items():
        if "/faq/" in url:
            continue
        base_url = re.sub(r"/[a-z]{2}/", "/", url)
        grouped_times[base_url].extend(times)

    unstable_pages = [
        (base_url, stdev(times))
        for base_url, times in grouped_times.items()
        if len(times) > 1
    ]
    return sorted(unstable_pages, key=lambda x: x[1], reverse=True)[:PAGES_TO_SHOW]


def get_error_prone_pages(errors):
    # Group URLs by base path, ignoring locale prefixes
    grouped_errors = defaultdict(list)
    for url, errs in errors.items():
        if "/faq/" in url:
            continue
        base_url = re.sub(r"/[a-z]{2}/", "/", url)
        grouped_errors[base_url].extend(errs)

    error_counts = [(base_url, len(errs)) for base_url, errs in grouped_errors.items()]
    return sorted(error_counts, key=lambda x: x[1], reverse=True)


def get_warning_prone_pages(warnings):
    # Group URLs by base path, ignoring locale prefixes
    grouped_warnings = defaultdict(list)
    for url, warns in warnings.items():
        if "/faq/" in url:
            continue
        base_url = re.sub(r"/[a-z]{2}/", "/", url)
        grouped_warnings[base_url].extend(warns)

    warning_counts = [
        (base_url, len(warns)) for base_url, warns in grouped_warnings.items()
    ]
    return sorted(warning_counts, key=lambda x: x[1], reverse=True)


def get_largest_pages(response_sizes):
    # Group URLs by base path, ignoring locale prefixes
    grouped_sizes = defaultdict(list)
    for url, sizes in response_sizes.items():
        if "/faq/" in url:
            continue
        base_url = re.sub(r"/[a-z]{2}/", "/", url)
        grouped_sizes[base_url].extend(sizes)

    avg_sizes = [(base_url, mean(sizes)) for base_url, sizes in grouped_sizes.items()]
    return sorted(avg_sizes, key=lambda x: x[1], reverse=True)[:PAGES_TO_SHOW]


def get_device_distribution(device_stats):
    # Group URLs by base path, ignoring locale prefixes
    grouped_devices = defaultdict(lambda: defaultdict(int))
    for url, devices in device_stats.items():
        if "/faq/" in url:
            continue
        base_url = re.sub(r"/[a-z]{2}/", "/", url)
        for device, count in devices.items():
            grouped_devices[base_url][device] += count

    distribution = {}
    for base_url, devices in grouped_devices.items():
        total = sum(devices.values())
        distribution[base_url] = {
            device: count / total * 100 for device, count in devices.items()
        }
    return distribution


def print_analysis(
    load_times, errors, warnings, response_sizes, device_stats, days_limit
):
    print(f"\n=== Website Performance Analysis for the last {days_limit} days ===\n")

    print(f"Top {PAGES_TO_SHOW} slowest pages (average load time):")
    for url, avg_time, max_time, min_time in get_slowest_pages(load_times):
        print(
            f"{url}: {avg_time:.2f} sec (Max: {max_time:.2f} sec, Min: {min_time:.2f} sec)"
        )

    print(f"\nTop {PAGES_TO_SHOW} most unstable pages (load time standard deviation):")
    for url, std in get_most_unstable_pages(load_times):
        print(f"{url}: ±{std:.2f} sec")

    print(f"\nTop {PAGES_TO_SHOW} largest pages (average size):")
    for url, size in get_largest_pages(response_sizes):
        print(f"{url}: {size / 1024:.1f} KB")

    if errors:
        print("\nPages with errors:")
        for url, count in get_error_prone_pages(errors):
            print(f"{url}: {count} errors")

    if warnings:
        print("\nPages with warnings:")
        for url, count in get_warning_prone_pages(warnings):
            print(f"{url}: {count} warnings")


def main():
    from config import LOG_FILE

    load_times, status_codes, errors, warnings, response_sizes, device_stats = (
        parse_logs(LOG_FILE)
    )
    print_analysis(
        load_times, errors, warnings, response_sizes, device_stats, DAYS_TO_ANALYZE
    )


if __name__ == "__main__":
    main()
