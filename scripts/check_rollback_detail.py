import sqlite3

conn = sqlite3.connect('/data/klepaas.db')
cursor = conn.cursor()

print("=" * 80)
print("K-Le-PaaS/test01 DETAILED ROLLBACK ANALYSIS")
print("=" * 80)

# 모든 성공한 배포 (is_rollback 포함)
print("\n[ALL SUCCESSFUL DEPLOYMENTS (including rollbacks)]")
cursor.execute("""
    SELECT id, github_commit_sha, is_rollback, created_at, deployed_at
    FROM deployment_histories
    WHERE github_owner='K-Le-PaaS' AND github_repo='test01' AND status='success'
    ORDER BY created_at DESC
""")
rows = cursor.fetchall()
print(f"Total: {len(rows)}")
for idx, row in enumerate(rows):
    print(f"{idx}: id={row[0]}, commit={row[1][:7]}, is_rollback={row[2]}, created_at={row[3]}, deployed_at={row[4]}")

# 원본 배포만 (is_rollback=0)
print("\n[ORIGINAL DEPLOYMENTS ONLY (is_rollback=0)]")
cursor.execute("""
    SELECT id, github_commit_sha, created_at, deployed_at
    FROM deployment_histories
    WHERE github_owner='K-Le-PaaS' AND github_repo='test01' AND status='success' AND is_rollback=0
    ORDER BY created_at DESC
""")
original_rows = cursor.fetchall()
print(f"Total: {len(original_rows)}")
for idx, row in enumerate(original_rows):
    print(f"{idx}: id={row[0]}, commit={row[1][:7]}, created_at={row[2]}, deployed_at={row[3]}")

# 시뮬레이션: 현재 배포 찾기
print("\n[ROLLBACK SIMULATION]")
cursor.execute("""
    SELECT id, github_commit_sha, is_rollback, created_at
    FROM deployment_histories
    WHERE github_owner='K-Le-PaaS' AND github_repo='test01' AND status='success'
    ORDER BY created_at DESC LIMIT 1
""")
current = cursor.fetchone()
print(f"Current deployment (most recent): id={current[0]}, commit={current[1][:7]}, is_rollback={current[2]}")

current_commit = current[1]
print(f"Current commit SHA: {current_commit}")

# 원본 타임라인에서 현재 커밋 찾기
current_index = None
for idx, row in enumerate(original_rows):
    if row[1] == current_commit:
        current_index = idx
        print(f"Found current commit in original timeline at index: {current_index}")
        break

if current_index is None:
    print("⚠️ Current commit NOT FOUND in original timeline!")
else:
    # 타겟 계산
    steps_back = 1
    target_index = current_index + steps_back
    print(f"Target calculation: {current_index} + {steps_back} = {target_index}")

    if target_index < len(original_rows):
        target = original_rows[target_index]
        print(f"Target deployment: id={target[0]}, commit={target[1][:7]}")
    else:
        print(f"⚠️ Target index {target_index} out of range (max: {len(original_rows)-1})")

conn.close()
