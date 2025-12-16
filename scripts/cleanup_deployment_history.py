"""
Cleanup script for deployment_histories table duplicates

This script:
1. Identifies duplicate deployment records (same commit with multiple rows)
2. Keeps the most recent record for each commit
3. Updates old "running" records to "success" if deployment likely succeeded
4. Generates a report of changes

Run after re-enabling kubernetes_watcher to clean up historical data.
"""

import sqlite3
from datetime import datetime, timedelta

DB_PATH = '/data/klepaas.db'

def main(auto_confirm=False):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    print("=" * 80)
    print("DEPLOYMENT HISTORY CLEANUP SCRIPT")
    print("=" * 80)
    if auto_confirm:
        print("[AUTO-CONFIRM MODE: Will automatically proceed with all cleanups]")

    # 1. Identify duplicates
    print("\n[STEP 1] Identifying duplicate records...")
    cursor.execute("""
        SELECT
            github_owner,
            github_repo,
            github_commit_sha,
            COUNT(*) as count,
            GROUP_CONCAT(id) as ids,
            GROUP_CONCAT(status) as statuses
        FROM deployment_histories
        WHERE github_owner IS NOT NULL
          AND github_repo IS NOT NULL
          AND github_commit_sha IS NOT NULL
        GROUP BY github_owner, github_repo, github_commit_sha
        HAVING COUNT(*) > 1
        ORDER BY count DESC
    """)

    duplicates = cursor.fetchall()
    print(f"Found {len(duplicates)} commits with duplicate records")

    if not duplicates:
        print("No duplicates found. Database is clean!")
        conn.close()
        return

    # 2. Show duplicates before cleanup
    total_to_delete = 0
    for owner, repo, sha, count, ids, statuses in duplicates:
        id_list = ids.split(',')
        status_list = statuses.split(',')
        total_to_delete += len(id_list) - 1  # Keep 1, delete rest

        print(f"\n  {owner}/{repo} - {sha[:7]}")
        print(f"    Records: {count} (will keep 1, delete {count-1})")
        print(f"    IDs: {ids}")
        print(f"    Statuses: {statuses}")

    print(f"\n[SUMMARY] Will delete {total_to_delete} duplicate records")

    # 3. Ask for confirmation
    if not auto_confirm:
        response = input("\nProceed with cleanup? (yes/no): ")
        if response.lower() != 'yes':
            print("Cleanup cancelled.")
            conn.close()
            return
    else:
        print("\n[AUTO-CONFIRM] Proceeding with cleanup...")

    # 4. Delete duplicates (keep most recent ID)
    print("\n[STEP 2] Removing duplicates...")
    deleted_count = 0

    for owner, repo, sha, count, ids, statuses in duplicates:
        id_list = [int(id_str) for id_str in ids.split(',')]

        # Keep the record with highest ID (most recent)
        ids_to_delete = sorted(id_list)[:-1]

        if ids_to_delete:
            placeholders = ','.join('?' for _ in ids_to_delete)
            cursor.execute(
                f"DELETE FROM deployment_histories WHERE id IN ({placeholders})",
                ids_to_delete
            )
            deleted_count += len(ids_to_delete)
            print(f"  Deleted IDs: {ids_to_delete} for {owner}/{repo}:{sha[:7]}")

    conn.commit()
    print(f"\n[RESULT] Deleted {deleted_count} duplicate records")

    # 5. Update old "running" records to "success"
    print("\n[STEP 3] Updating stale 'running' records...")

    # Get current time
    now = datetime.utcnow()
    ten_minutes_ago = (now - timedelta(minutes=10)).strftime('%Y-%m-%d %H:%M:%S')

    cursor.execute("""
        SELECT id, github_owner, github_repo, github_commit_sha, created_at
        FROM deployment_histories
        WHERE status = 'running'
          AND created_at < ?
        ORDER BY created_at DESC
    """, (ten_minutes_ago,))

    stale_running = cursor.fetchall()
    print(f"Found {len(stale_running)} stale 'running' records (>10 minutes old)")

    if stale_running:
        print("\nStale records:")
        for id, owner, repo, sha, created_at in stale_running:
            print(f"  ID={id}: {owner}/{repo} {sha[:7] if sha else 'None'} | created={created_at}")

        proceed_update = auto_confirm
        if not auto_confirm:
            response = input("\nUpdate these to 'success' status? (yes/no): ")
            proceed_update = response.lower() == 'yes'
        else:
            print("\n[AUTO-CONFIRM] Updating to 'success' status...")

        if proceed_update:
            for id, owner, repo, sha, created_at in stale_running:
                cursor.execute("""
                    UPDATE deployment_histories
                    SET status = 'success',
                        deployed_at = created_at,
                        completed_at = created_at
                    WHERE id = ?
                """, (id,))

            conn.commit()
            print(f"\n[RESULT] Updated {len(stale_running)} records to 'success'")
        else:
            print("Update skipped.")

    # 6. Final statistics
    print("\n" + "=" * 80)
    print("CLEANUP COMPLETE - FINAL STATISTICS")
    print("=" * 80)

    cursor.execute("SELECT COUNT(*) FROM deployment_histories")
    total = cursor.fetchone()[0]
    print(f"\nTotal deployment records: {total}")

    cursor.execute("SELECT status, COUNT(*) FROM deployment_histories GROUP BY status")
    status_counts = cursor.fetchall()
    print("\nStatus breakdown:")
    for status, count in status_counts:
        print(f"  {status}: {count}")

    # Check for remaining duplicates
    cursor.execute("""
        SELECT COUNT(*) FROM (
            SELECT github_owner, github_repo, github_commit_sha
            FROM deployment_histories
            WHERE github_owner IS NOT NULL
              AND github_repo IS NOT NULL
              AND github_commit_sha IS NOT NULL
            GROUP BY github_owner, github_repo, github_commit_sha
            HAVING COUNT(*) > 1
        )
    """)
    remaining_dupes = cursor.fetchone()[0]

    if remaining_dupes == 0:
        print("\n[OK] No duplicate records remaining!")
    else:
        print(f"\n[WARNING] {remaining_dupes} duplicates still exist")

    conn.close()
    print("\n" + "=" * 80)

if __name__ == '__main__':
    import sys
    auto_confirm = '--auto-confirm' in sys.argv or '-y' in sys.argv
    main(auto_confirm=auto_confirm)
