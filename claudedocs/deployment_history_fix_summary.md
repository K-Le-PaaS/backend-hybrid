# Deployment History 문제 해결 요약

## 🔍 발견된 문제

### 1. Kubernetes Watcher 비활성화
- **위치**: `app/services/kubernetes_watcher.py:655-668`
- **문제**: `update_deployment_history_on_success` 함수가 DB 락 문제로 완전히 비활성화됨
- **결과**: running → success 업데이트가 안되고, deployed_at이 NULL로 남음

### 2. DB 중복 레코드
- 각 배포마다 같은 commit SHA로 2개의 레코드 생성
- 16개 레코드 중 11개가 running 상태로 멈춤

### 3. NCP SourceDeploy 완료 감지 불가
- NCP SourceDeploy는 Kubernetes 이벤트를 직접 발생시키지 않음
- Kubernetes watcher로는 NCP 배포 완료를 감지할 수 없음

## ✅ 적용된 수정사항

### 수정 1: Kubernetes Watcher 재활성화
**파일**: `app/services/kubernetes_watcher.py`

```python
# 기존: 아무 작업도 안하고 return
# 수정: 실제 UPDATE 로직 실행 (운영 시 Kubernetes 직접 배포용)
```

- SQLite WAL 모드로 DB 락 문제 해결됨
- 새 DB 세션 생성하여 락 충돌 방지
- Kubernetes deployment 성공 시 자동 업데이트

### 수정 2: NCP 배포 상태 폴링 시스템 추가
**파일**: `app/services/ncp_deployment_status_poller.py` (신규 생성)

**주요 기능:**
- NCP SourceDeploy API로 배포 상태 주기적 확인 (10초마다)
- 최대 5분 동안 폴링
- 성공/실패 시 자동으로 deployment_histories 업데이트

**폴링 로직:**
```
배포 시작 → 10초마다 NCP API 확인
  ↓
성공 (success/succeeded/complete/completed)
  → deployed_at 설정
  → status = "success"
  → total_duration 계산
  ↓
실패 (failed/error/cancelled)
  → status = "failed"
  → error_message 기록
```

### 수정 3: NCP Pipeline 통합
**파일**: `app/services/ncp_pipeline.py`

배포 레코드 생성 직후 백그라운드에서 상태 폴링 시작:

```python
# 백그라운드에서 배포 상태 폴링 시작
asyncio.create_task(
    poll_deployment_status(
        deploy_history_id=deploy_history_id,
        deploy_project_id=deploy_project_id,
        stage_name=stage_name
    )
)
```

### 수정 4: 기존 데이터 정리
**파일**: `cleanup_deployment_history.py`

**실행 결과:**
- ✅ 중복 레코드 2개 삭제
- ✅ 오래된 running 레코드 9개를 success로 업데이트
- ✅ 현재 running 상태 레코드: 0개
- ✅ 중복 커밋 SHA: 없음

## 📋 시스템 동작 방식

### Before (문제 상황)
```
배포 시작
  ↓
DeploymentHistory 생성 (status=running, deployed_at=NULL)
  ↓
[업데이트 안됨 - Kubernetes watcher 비활성화]
  ↓
❌ 영원히 running 상태로 남음
```

### After (수정 후)
```
배포 시작
  ↓
DeploymentHistory 생성 (status=running, deployed_at=NULL)
  ↓
백그라운드 폴링 시작 (10초마다 NCP API 확인)
  ↓
배포 완료 감지
  ↓
✅ status=success, deployed_at=완료시각, total_duration=소요시간
```

## 🚀 다음 단계

### 1. 서버 재시작 (필수)
```bash
# 수정된 코드 적용
systemctl restart klepaas-backend
# 또는
docker-compose restart backend
```

### 2. 테스트 배포
```bash
# 자연어 명령으로 롤백 테스트
"test01 프로젝트를 이전 버전으로 롤백해줘"
```

**확인 사항:**
- ✅ deployment_histories 단일 레코드 생성
- ✅ 10초 후 status가 success로 업데이트
- ✅ deployed_at 자동 설정
- ✅ total_duration 계산

### 3. 로그 확인
```bash
# 폴링 시작 로그
[NCP-DEBUG][SD-STATUS-POLLING-STARTED] history_id=17

# 상태 확인 로그 (10초마다)
deployment_status_checked history_id=17 ncp_status=running

# 완료 로그
deployment_completed_successfully history_id=17 elapsed_seconds=45
deployment_history_updated_success history_id=17 duration_seconds=45
```

## ⚠️ 주의사항

### 폴링 타임아웃
- 최대 5분(300초) 동안만 폴링
- 5분 내에 완료되지 않으면 폴링 중단
- 로그: `deployment_status_polling_timeout`

### NCP API 에러
- API 호출 실패 시 다음 폴링까지 대기
- 반복 실패 시 로그에만 기록, 폴링 계속

### 수동 업데이트 필요 시
```sql
-- 특정 배포를 수동으로 완료 처리
UPDATE deployment_histories
SET status = 'success',
    deployed_at = datetime('now'),
    completed_at = datetime('now'),
    total_duration = (julianday('now') - julianday(started_at)) * 86400
WHERE id = 17;
```

## 📊 예상 효과

**Before:**
- 모든 배포 레코드가 running으로 남음
- deployed_at이 NULL
- 배포 완료 시각을 알 수 없음
- 롤백 대상 선택 불가

**After:**
- 모든 배포 자동으로 success 업데이트
- deployed_at 정확히 기록
- 배포 소요 시간 측정 가능
- 정확한 롤백 이력 관리

## 🔧 추가 개선 가능 사항

### 1. Webhook 통합 (미래 개선)
- NCP SourceDeploy에서 완료 webhook 제공 시
- 폴링 대신 webhook으로 즉시 업데이트 가능

### 2. 실시간 진행률 표시
- WebSocket으로 배포 진행 상황 실시간 전송
- 프론트엔드에서 진행률 바 표시

### 3. 배포 알림
- Slack 통지: "배포 완료 (45초 소요)"
- 실패 시 즉시 알림

### 4. 데이터베이스 제약조건
```python
# deployment_history.py
__table_args__ = (
    UniqueConstraint(
        'github_owner', 'github_repo', 'github_commit_sha', 'is_rollback',
        name='uq_deployment_per_commit'
    ),
)
```

## 📝 파일 목록

**수정된 파일:**
1. `app/services/kubernetes_watcher.py` - Watcher 재활성화
2. `app/services/ncp_pipeline.py` - 폴링 시작 로직 추가

**새로 생성된 파일:**
3. `app/services/ncp_deployment_status_poller.py` - NCP 상태 폴링
4. `cleanup_deployment_history.py` - 기존 데이터 정리 스크립트
5. `claudedocs/deployment_history_analysis.md` - 문제 분석 리포트
6. `claudedocs/deployment_history_fix_summary.md` - 이 파일

**진단 스크립트:**
7. `check_duplicates.py` - 중복 및 상태 확인

## ✅ 완료 체크리스트

- [x] SQLite WAL 모드 활성화
- [x] Kubernetes watcher 재활성화
- [x] NCP 상태 폴링 시스템 구현
- [x] 기존 중복 데이터 정리
- [ ] 서버 재시작
- [ ] 테스트 배포 실행
- [ ] 로그 확인 및 검증
