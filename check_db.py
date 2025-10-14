import sqlite3

conn = sqlite3.connect('test.db')
cursor = conn.cursor()

# 테이블 목록 확인
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()
print('Available Tables:')
for table in tables:
    print(f'- {table[0]}')

# deployment_histories 테이블이 있다면 스키마 확인
if any('deployment_histories' in table for table in tables):
    print('\nDeployment Histories Table Schema:')
    cursor.execute("PRAGMA table_info(deployment_histories)")
    columns = cursor.fetchall()
    for col in columns:
        print(f'{col[1]}: {col[2]}')
    
    # 데이터 확인
    print('\nDeployment Histories Data:')
    cursor.execute("SELECT id, status, sourcecommit_status, sourcebuild_status, sourcedeploy_status FROM deployment_histories ORDER BY id DESC LIMIT 5")
    rows = cursor.fetchall()
    for row in rows:
        print(f'ID: {row[0]}, Status: {row[1]}, SourceCommit: {row[2]}, SourceBuild: {row[3]}, SourceDeploy: {row[4]}')

conn.close()