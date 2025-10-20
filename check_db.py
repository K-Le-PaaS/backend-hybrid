import sqlite3

conn = sqlite3.connect('/data/klepaas.db')
cursor = conn.cursor()

print("=" * 80)
print("DATABASE: /data/klepaas.db")
print("=" * 80)

# 테이블 목록 확인
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()
table_names = [table[0] for table in tables]
print('\nAvailable Tables:')
for table in table_names:
    print(f'- {table}')

# user_project_integrations 테이블 확인
if 'user_project_integrations' in table_names:
    print("\n" + "=" * 80)
    print("USER_PROJECT_INTEGRATIONS TABLE")
    print("=" * 80)

    # 스키마 확인
    cursor.execute("PRAGMA table_info(user_project_integrations)")
    columns = cursor.fetchall()
    print("\nSchema:")
    for col in columns:
        print(f"  {col[1]}: {col[2]}")

    # 데이터 확인
    cursor.execute("SELECT user_id, github_owner, github_repo, github_full_name, build_project_id, deploy_project_id FROM user_project_integrations")
    rows = cursor.fetchall()
    print(f"\nTotal rows: {len(rows)}")
    print("\nData:")
    for row in rows:
        print(f"  user_id={row[0]}, owner={row[1]}, repo={row[2]}, full_name={row[3]}, build_id={row[4]}, deploy_id={row[5]}")

    # K-Le-PaaS/test01 특정 조회
    print("\n" + "-" * 80)
    print("K-Le-PaaS/test01 Integration:")
    cursor.execute("SELECT * FROM user_project_integrations WHERE github_owner='K-Le-PaaS' AND github_repo='test01'")
    rows = cursor.fetchall()
    if rows:
        for row in rows:
            print(f"  Found: {row}")
    else:
        print("  NOT FOUND")

# deployment_history 또는 deployment_histories 테이블 확인
deployment_table = None
if 'deployment_history' in table_names:
    deployment_table = 'deployment_history'
elif 'deployment_histories' in table_names:
    deployment_table = 'deployment_histories'

if deployment_table:
    print("\n" + "=" * 80)
    print(f"{deployment_table.upper()} TABLE")
    print("=" * 80)

    # 스키마 확인
    cursor.execute(f"PRAGMA table_info({deployment_table})")
    columns = cursor.fetchall()
    print("\nSchema:")
    for col in columns:
        print(f"  {col[1]}: {col[2]}")

    # 데이터 확인 (최근 10개)
    cursor.execute(f"SELECT github_owner, github_repo, github_commit_sha, status, deployed_at, is_rollback FROM {deployment_table} ORDER BY created_at DESC LIMIT 10")
    rows = cursor.fetchall()
    print(f"\nTotal rows shown: {len(rows)}")
    print("\nRecent deployments:")
    for row in rows:
        print(f"  {row[0]}/{row[1]} | commit={row[2][:7] if row[2] else 'None'} | status={row[3]} | deployed_at={row[4]} | is_rollback={row[5]}")

    # K-Le-PaaS/test01 특정 조회
    print("\n" + "-" * 80)
    print("K-Le-PaaS/test01 Deployment History:")
    cursor.execute(f"SELECT COUNT(*) FROM {deployment_table} WHERE github_owner='K-Le-PaaS' AND github_repo='test01' AND status='success' AND is_rollback=0")
    count = cursor.fetchone()[0]
    print(f"  Successful deployments (non-rollback): {count}")

    cursor.execute(f"SELECT github_commit_sha, status, deployed_at, created_at FROM {deployment_table} WHERE github_owner='K-Le-PaaS' AND github_repo='test01' ORDER BY created_at DESC LIMIT 5")
    rows = cursor.fetchall()
    if rows:
        print("  Recent 5 deployments:")
        for row in rows:
            print(f"    commit={row[0][:7] if row[0] else 'None'} | status={row[1]} | deployed_at={row[2]} | created_at={row[3]}")
    else:
        print("  NO DEPLOYMENTS FOUND")

conn.close()
print("\n" + "=" * 80)