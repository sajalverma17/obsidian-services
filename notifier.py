import os
import re
import requests
import sys
import argparse
import time
from datetime import datetime

COUCHDB_USER = os.getenv('COUCHDB_USER')
COUCHDB_PASSWORD = os.getenv('COUCHDB_PASSWORD')
COUCHDB_BASE_URL = os.getenv('COUCHDB_BASE_URL')
COUCHDB_DATABASE = os.getenv('COUCHDB_DATABASE')

COUCHDB_AUTH = (COUCHDB_USER, COUCHDB_PASSWORD)

POLL_INTERVAL_SECONDS = 600
# Tolerance window because if first poll is at t-00:01, next may happen at t+10:01 instead of t+09:59 due to random drifts
DRIFT_TOLERANCE_SECONDS = 10

def read_from_couchdb(file_path):
    try:
        print(f"Reading '{file_path}' from CouchDB...")
        find_url = f"{COUCHDB_BASE_URL}/{COUCHDB_DATABASE}/_find"
        query = {"selector": {"path": file_path}}
        response = requests.post(find_url, json=query, auth=COUCHDB_AUTH, timeout=10).json()

        docs = response.get('docs', [])
        if not docs:
            print(f"Error: File '{file_path}' not found on CouchDB.")
            return None

        doc_metadata = docs[0]
        chunk_ids = doc_metadata.get('children', [])

        file_text = "".join([
            requests.get(f"{COUCHDB_BASE_URL}/{COUCHDB_DATABASE}/{c_id}", auth=COUCHDB_AUTH, timeout=5).json().get('data', '')
            for c_id in chunk_ids
        ])

        return file_text.splitlines()

    except Exception as ex:
        print(f"Error: Unable to construct '{file_path}' from CouchDB: '{ex}'.")
        return None

def read_file(file_path):
    return read_from_couchdb(file_path)


def process_todos(file_path):
    # Match unchecked items (- [ ] Task name)
    todo_pattern = re.compile(r'^\s*-\s*\[ \]\s*(.*)$')
    # Match @ YYYY-MM-DD HH:MM (Task name @ 2024-06-30 14:00)
    datetime_pattern = re.compile(r'@ (\d{4}-\d{2}-\d{2} \d{2}:\d{2})')
    # Match @ HH:MM only (Task name @ 15:00)
    time_only_pattern = re.compile(r'@ (\d{2}:\d{2})\s*$')
    todos = []

    lines = read_file(file_path)

    for line in lines:
        match = todo_pattern.match(line)
        if match:
            todo_text = match.group(1).strip()
            if todo_text:
                datetime_match = datetime_pattern.search(todo_text)
                time_only_match = time_only_pattern.search(todo_text)
                if datetime_match and datetime_match.group(1):
                    try:
                        now = datetime.now()
                        due = datetime.strptime(datetime_match.group(1), '%Y-%m-%d %H:%M')
                        # Notify if due time passed within last 10 mins (+ drift), once per day (modulo 86400s)
                        if due <= now and (now - due).total_seconds() % 86400 <= POLL_INTERVAL_SECONDS + DRIFT_TOLERANCE_SECONDS:
                            todos.append(todo_text)
                    except ValueError:
                        print(f"Warning: Invalid datetime format in line: {line.strip()}")
                elif time_only_match and time_only_match.group(1):
                    try:
                        now = datetime.now()
                        due = datetime.strptime(time_only_match.group(1), '%H:%M').replace(year=now.year, month=now.month, day=now.day)
                        # Same daily check
                        if due <= now and (now - due).total_seconds() <= POLL_INTERVAL_SECONDS + DRIFT_TOLERANCE_SECONDS:
                            todos.append(todo_text)
                    except ValueError:
                        print(f"Warning: Invalid time format in line: {line.strip()}")

    return todos

def send_notification(server_url, topic, message):
    base_url = server_url.rstrip('/')
    url = f"{base_url}/{topic}"
    try:
        response = requests.post(
            url,
            data=message.encode('utf-8'),
            headers={"Markdown": "yes"},
            timeout=10  # timeout prevents the script from hanging indefinitely
        )
        return response.status_code == 200
    except Exception as ex:
        print(f"Error: Network error when sending notification: {ex}")
        return False

def run(server_url, file_path, topic):
    print(f"\n🚀 Scanning due tasks...")

    tasks = process_todos(file_path)
    if not tasks:
        print(f"No tasks due.")
    else:
        success_count = 0
        for task in tasks:
            if send_notification(server_url, topic, task):
                print(f"Sent notification for: {task}")
                success_count += 1
            else:
                print(f"Failed to notify for: {task}")

        print(f"✅Finished: {success_count}/{len(tasks)} tasks notified.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Send unchecked Markdown tasks as notifications to ntfy")
    parser.add_argument("server_url", help="ntfy server URL (e.g., https://ntfy.sh or http://100.x.y.z:5985)")
    parser.add_argument("file", help="Path to the Markdown file")
    parser.add_argument("topic", help="ntfy topic name")
    parser.add_argument("--loop", action="store_true", help="Run every 10 minutes")

    args = parser.parse_args()

    try:
        while True:
            run(args.server_url, args.file, args.topic)
            if not args.loop:
                break

            print(f"Sleeping for {POLL_INTERVAL_SECONDS}s...")
            time.sleep(POLL_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)
