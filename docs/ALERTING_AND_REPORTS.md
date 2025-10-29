## Alerting and Snapshot Reports (Infra Monitoring)

### Overview
Infrastructure alerts are generated from Prometheus (nks-prometheus) and shown in the dashboard. Clicking Details creates a time-stamped snapshot report capturing node metrics and thresholds, stored in DB.

### Data Flow
- Prometheus → API `/api/v1/monitoring/alerts` → Frontend Alerts tab
- Details → API `/api/v1/monitoring/alerts/{alert_id}/snapshot` → Report modal (and DB persist)
- Resolve → API `/api/v1/monitoring/alerts/{alert_id}/resolve` → Mark as resolved (DB only) and move to resolved group in UI

### Models
- `app/models/notification.py`
  - `Notification(id, title, description, severity, source, status, labels, created_at, resolved_at)`
  - `NotificationReport(id, notification_id, cluster, summary, snapshot_json, created_at)`

### Endpoints
- GET `/api/v1/monitoring/alerts`
  - Returns active alerts derived from Prometheus + any firing alerts saved in DB.
  - Prometheus-derived rules (cluster param default `nks-cluster`):
    - Memory: `(1 - MemAvailable / MemTotal) * 100 > 85`
    - Disk `/`: usage > 90 (exclude `rootfs`)
    - Pod restarts: `increase(kube_pod_container_status_restarts_total[1h]) > 5`
- POST `/api/v1/monitoring/alerts/{alert_id}/snapshot`
  - Generates and persists a `NotificationReport` from current metrics (reuses `get_monitoring_details`).
  - Response: `{ report_id, notification_id, created_at, summary, snapshot }`.
- GET `/api/v1/monitoring/alert-reports/{report_id}`
- GET `/api/v1/monitoring/alerts/{alert_id}/reports?limit=20`
- POST `/api/v1/monitoring/alerts/{alert_id}/resolve`
  - Sets `status=resolved` and `resolved_at` for DB-backed alerts; Prometheus-only alerts return noop but UI still moves them to resolved group.

### Prometheus Integration
- Service: `app/services/notification_service.py`
  - `list_active_alerts(cluster)` is async and queries Prometheus via `query_prometheus(PromQuery)`.
  - It deduplicates alerts by id, merges DB firing alerts, and returns the final list.
  - If no live alerts exist, returns 4 example alerts (temporary UI fallback) which disappear as soon as real alerts exist.
  - `generate_report_from_current_state(notification, cluster)` builds a snapshot:
    - `cluster`, `generated_at`, `alert{...}`
    - `nodes[]` with CPU, Memory, Disk, Network, and derived `alerts{severity, reasons}`
    - `thresholds`: `{ cpu_pct:80, mem_pct:80, disk_root_pct:85, iowait_pct:5, io_sat:0.8 }`
  - `resolve_alert(alert_id)` changes DB `Notification.status` to `resolved`.

### Frontend Wiring
- File: `frontend/components/real-time-monitoring-dashboard.tsx`
  - Replaced hardcoded alerts with API fetch.
  - Grouped rendering:
    - Unresolved (status != resolved) → time desc
    - Resolved (status == resolved) → time desc, card opacity reduced
  - Details: calls snapshot API; shows modal with summary, node metrics, thresholds; copy/download JSON.
  - Resolve: calls resolve API and updates local state immediately to move the card.
- API client additions: `frontend/lib/api.ts`
  - `getAlerts(cluster)`, `createAlertSnapshot(alertId, cluster)`, `getAlertReport(reportId)`, `getAlertReports(alertId, limit)`, `resolveAlert(alertId, reason?)`.

### Migrations
- Alembic: `alembic/versions/003_add_notifications.py` creates `notifications` and `notification_reports` with indexes and FK.
- Models imported in `app/main.py` and `app/database.py` so tables are created/available.

### Testing
1. Alerts list (no real alerts): GET `/api/v1/monitoring/alerts` should return 4 example alerts.
2. With Prometheus configured (`prometheus_base_url`), alerts should reflect live metrics.
3. Snapshot: POST `/api/v1/monitoring/alerts/{id}/snapshot` and verify response includes `report_id` and persisted record.
4. Resolve: POST `/api/v1/monitoring/alerts/{id}/resolve` then GET alerts to see it under resolved group.
5. UI: Open Dashboard → Alerts tab → verify grouping, Details modal, Resolve behavior.

### Future Enhancements
- Replace example alerts fallback with Alertmanager API source.
- Externalize thresholds to settings and per-tenant policy.
- Add "Acknowledge" state and filter tabs.

