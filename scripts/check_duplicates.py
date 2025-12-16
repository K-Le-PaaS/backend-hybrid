import sqlite3
from datetime import datetime

conn = sqlite3.connect('/data/klepaas.db')
cursor = conn.cursor()

print("=" * 80)
print("DEPLOYMENT HISTORIES - DUPLICATE ANALYSIS")
print("=" * 80)

# 1. 전체 통계
cursor.execute("SELECT COUNT(*) FROM deployment_histories")
total = cursor.fetchone()[0]
print(f"\n[TOTAL] Deployment records: {total}")

# 2. 상태별 통계
cursor.execute("SELECT status, COUNT(*) FROM deployment_histories GROUP BY status")
status_counts = cursor.fetchall()
print("\n[STATUS] Status breakdown:")
for status, count in status_counts:
    print(f"  {status}: {count}")

# 3. 같은 커밋에 대한 중복 기록 확인 
print("\n" + "=" * 80)
print("[DUPLICATES] Same commit SHA duplicates")
print("=" * 80)
cursor.execute("""
    SELECT
        github_owner,
        github_repo,
        github_commit_sha,
        COUNT(*) as count,
        GROUP_CONCAT(status) as statuses,
        GROUP_CONCAT(id) as ids
    FROM deployment_histories
    WHERE github_owner IS NOT NULL AND github_repo IS NOT NULL
    GROUP BY github_owner, github_repo, github_commit_sha
    HAVING COUNT(*) > 1
    ORDER BY count DESC
""")
duplicates = cursor.fetchall()

if duplicates:
    print(f"\n중복된 커밋 수: {len(duplicates)}")
    for dup in duplicates:
        owner, repo, sha, count, statuses, ids = dup
        print(f"\n  {owner}/{repo} - {sha[:7]}")
        print(f"    중복 횟수: {count}")
        print(f"    상태들: {statuses}")
        print(f"    ID들: {ids}")

        # 각 ID별 상세 정보
        id_list = ids.split(',')
        cursor.execute(f"""
            SELECT id, status, is_rollback, created_at, started_at, deployed_at
            FROM deployment_histories
            WHERE id IN ({','.join(id_list)})
            ORDER BY created_at
        """)
        details = cursor.fetchall()
        for detail in details:
            print(f"      ID={detail[0]}: status={detail[1]}, rollback={detail[2]}, created={detail[3]}, deployed={detail[5]}")
else:
    print("\n[OK] No commit SHA duplicates")

# 4. deployed_at이 NULL인 success 상태 확인
print("\n" + "=" * 80)
print("[WARNING] Success deployments with NULL deployed_at")
print("=" * 80)
cursor.execute("""
    SELECT id, github_owner, github_repo, github_commit_sha, status, created_at, deployed_at
    FROM deployment_histories
    WHERE status = 'success' AND deployed_at IS NULL
    ORDER BY created_at DESC
    LIMIT 10
""")
null_deployed = cursor.fetchall()
print(f"\nSuccess인데 deployed_at이 NULL: {len(null_deployed)}개")
for row in null_deployed:
    print(f"  ID={row[0]}: {row[1]}/{row[2]} {row[3][:7]} | created={row[5]} | deployed={row[6]}")

# 5. running 상태로 남아있는 배포들
print("\n" + "=" * 80)
print("[RUNNING] Deployments stuck in running state")
print("=" * 80)
cursor.execute("""
    SELECT id, github_owner, github_repo, github_commit_sha, is_rollback, created_at
    FROM deployment_histories
    WHERE status = 'running'
    ORDER BY created_at DESC
""")
running = cursor.fetchall()
print(f"\nrunning 상태 배포: {len(running)}개")
for row in running:
    rollback_str = "롤백" if row[4] else "일반"
    print(f"  ID={row[0]}: {row[1]}/{row[2]} {row[3][:7] if row[3] else 'None'} [{rollback_str}] | created={row[5]}")

# 6. 시간순 배포 흐름 (최근 15개)
print("\n" + "=" * 80)
print("[TIMELINE] Recent 15 deployments")
print("=" * 80)
cursor.execute("""
    SELECT id, github_commit_sha, status, is_rollback, created_at
    FROM deployment_histories
    ORDER BY created_at DESC
    LIMIT 15
""")
timeline = cursor.fetchall()
for row in timeline:
    sha_short = row[1][:7] if row[1] else 'None'
    rollback = "[RB]" if row[3] else "    "
    print(f"  {rollback} ID={row[0]}: {sha_short} | {row[2]:8s} | {row[4]}")

conn.close()
print("\n" + "=" * 80)
