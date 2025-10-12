#!/usr/bin/env python3
"""
데이터베이스 상태 확인 스크립트
"""

import sqlite3
import os

def check_database():
    db_path = "C:/data/klepaas.db"
    
    if not os.path.exists(db_path):
        print(f"[ERROR] 데이터베이스 파일이 존재하지 않습니다: {db_path}")
        return
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 테이블 목록 확인
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        print(f"[INFO] 테이블 목록: {[table[0] for table in tables]}")
        
        # user_project_integrations 테이블 확인
        if ('user_project_integrations',) in tables:
            cursor.execute("SELECT COUNT(*) FROM user_project_integrations")
            count = cursor.fetchone()[0]
            print(f"[INFO] user_project_integrations 레코드 수: {count}")
            
            if count > 0:
                cursor.execute("SELECT id, user_id, github_full_name, created_at FROM user_project_integrations ORDER BY id DESC LIMIT 5")
                records = cursor.fetchall()
                print("[INFO] 최근 레코드들:")
                for record in records:
                    print(f"  - ID: {record[0]}, User: {record[1]}, Repo: {record[2]}, Created: {record[3]}")
        else:
            print("[ERROR] user_project_integrations 테이블이 존재하지 않습니다.")
        
        conn.close()
        print("[SUCCESS] 데이터베이스 연결 성공")
        
    except Exception as e:
        print(f"[ERROR] 데이터베이스 확인 중 오류: {e}")

if __name__ == "__main__":
    check_database()
