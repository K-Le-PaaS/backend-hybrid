# 알림 및 스냅샷 리포트 (인프라 모니터링)

> **배경 및 목적**: Prometheus에서 생성된 인프라 알림을 대시보드에 표시하고, 상세 정보를 클릭하면 타임스탬프가 포함된 스냅샷 리포트를 생성하여 노드 메트릭과 임계값을 데이터베이스에 저장하는 기능을 설명합니다.

---

## 개요

인프라 알림은 Prometheus(nks-prometheus)에서 생성되어 대시보드에 표시됩니다. 상세 정보를 클릭하면 타임스탬프가 포함된 스냅샷 리포트가 생성되어 노드 메트릭과 임계값을 캡처하고 데이터베이스에 저장됩니다.

---

## 데이터 흐름

- Prometheus → API `/api/v1/monitoring/alerts` → 프론트엔드 알림 탭
- 상세 정보 → API `/api/v1/monitoring/alerts/{alert_id}/snapshot` → 리포트 모달 (및 DB 저장)
- 해결 → API `/api/v1/monitoring/alerts/{alert_id}/resolve` → 해결됨으로 표시 (DB만) 및 UI에서 해결된 그룹으로 이동

---

## 데이터 모델

- `app/models/notification.py`
  - `Notification(id, title, description, severity, source, status, labels, created_at, resolved_at)`
  - `NotificationReport(id, notification_id, cluster, summary, snapshot_json, created_at)`

---

## API 엔드포인트

### GET `/api/v1/monitoring/alerts`
- Prometheus에서 파생된 활성 알림과 DB에 저장된 모든 발생 중인 알림을 반환합니다.
- Prometheus 파생 규칙 (클러스터 파라미터 기본값 `nks-cluster`):
  - 메모리: `(1 - MemAvailable / MemTotal) * 100 > 85`
  - 디스크 `/`: 사용률 > 90 (`rootfs` 제외)
  - Pod 재시작: `increase(kube_pod_container_status_restarts_total[1h]) > 5`

### POST `/api/v1/monitoring/alerts/{alert_id}/snapshot`
- 현재 메트릭에서 `NotificationReport`를 생성하고 저장합니다 (`get_monitoring_details` 재사용).
- 응답: `{ report_id, notification_id, created_at, summary, snapshot }`

### GET `/api/v1/monitoring/alert-reports/{report_id}`
- 특정 리포트 ID로 리포트를 조회합니다.

### GET `/api/v1/monitoring/alerts/{alert_id}/reports?limit=20`
- 특정 알림에 대한 리포트 목록을 조회합니다 (최대 20개).

### POST `/api/v1/monitoring/alerts/{alert_id}/resolve`
- DB 기반 알림의 경우 `status=resolved` 및 `resolved_at`을 설정합니다.
- Prometheus 전용 알림의 경우 noop을 반환하지만 UI에서는 여전히 해결된 그룹으로 이동합니다.

---

## Prometheus 연동

### 서비스: `app/services/notification_service.py`

- **`list_active_alerts(cluster)`**
  - 비동기 함수로 `query_prometheus(PromQuery)`를 통해 Prometheus를 쿼리합니다.
  - ID별로 알림을 중복 제거하고, DB의 발생 중인 알림을 병합하여 최종 목록을 반환합니다.
  - 활성 알림이 없으면 4개의 예제 알림을 반환합니다 (임시 UI 폴백). 실제 알림이 생기면 즉시 사라집니다.

- **`generate_report_from_current_state(notification, cluster)`**
  - 스냅샷을 생성합니다:
    - `cluster`, `generated_at`, `alert{...}`
    - `nodes[]` - CPU, Memory, Disk, Network 및 파생된 `alerts{severity, reasons}` 포함
    - `thresholds`: `{ cpu_pct:80, mem_pct:80, disk_root_pct:85, iowait_pct:5, io_sat:0.8 }`

- **`resolve_alert(alert_id)`**
  - DB의 `Notification.status`를 `resolved`로 변경합니다.

---

## 프론트엔드 연동

### 파일: `frontend/components/real-time-monitoring-dashboard.tsx`

- 하드코딩된 알림을 API 가져오기로 교체했습니다.
- 그룹화된 렌더링:
  - 미해결 (status != resolved) → 시간 내림차순
  - 해결됨 (status == resolved) → 시간 내림차순, 카드 투명도 감소
- 상세 정보: 스냅샷 API 호출; 요약, 노드 메트릭, 임계값을 포함한 모달 표시; JSON 복사/다운로드
- 해결: 해결 API 호출 및 로컬 상태를 즉시 업데이트하여 카드 이동

### API 클라이언트 추가: `frontend/lib/api.ts`

- `getAlerts(cluster)`, `createAlertSnapshot(alertId, cluster)`, `getAlertReport(reportId)`, `getAlertReports(alertId, limit)`, `resolveAlert(alertId, reason?)`

---

## 데이터베이스 마이그레이션

- Alembic: `alembic/versions/003_add_notifications.py`가 인덱스와 외래 키를 포함하여 `notifications` 및 `notification_reports` 테이블을 생성합니다.
- 모델은 `app/main.py`와 `app/database.py`에서 import되어 테이블이 생성/사용 가능합니다.

---

## 테스트

1. **알림 목록 (실제 알림 없음)**: GET `/api/v1/monitoring/alerts`는 4개의 예제 알림을 반환해야 합니다.
2. **Prometheus 구성됨 (`prometheus_base_url`)**: 알림은 실시간 메트릭을 반영해야 합니다.
3. **스냅샷**: POST `/api/v1/monitoring/alerts/{id}/snapshot`을 호출하고 응답에 `report_id`와 저장된 레코드가 포함되는지 확인합니다.
4. **해결**: POST `/api/v1/monitoring/alerts/{id}/resolve`를 호출한 후 GET 알림을 호출하여 해결된 그룹에 표시되는지 확인합니다.
5. **UI**: 대시보드 → 알림 탭 열기 → 그룹화, 상세 정보 모달, 해결 동작 확인

---

## 향후 개선 사항

- 예제 알림 폴백을 Alertmanager API 소스로 교체
- 임계값을 설정으로 외부화하고 테넌트별 정책 추가
- "확인됨" 상태 및 필터 탭 추가

---

**관련 문서**:
- [트러블슈팅 인덱스](./README.md)
- [롤백 에러 분석](./ROLLBACK_ERROR_ANALYSIS.md)
