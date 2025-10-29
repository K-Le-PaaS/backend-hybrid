"""
알림 및 보고서 관리 서비스

모니터링 알림을 관리하고 스냅샷 보고서를 생성하는 서비스입니다.
"""

import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any

import structlog
from sqlalchemy.orm import Session
from sqlalchemy import desc

from .monitoring import PromQuery, query_prometheus

from ..models.notification import Notification, NotificationReport

logger = structlog.get_logger(__name__)

# KST 타임존
KST = timezone(timedelta(hours=9))

def get_kst_now():
    """현재 한국 시간(KST) 반환"""
    return datetime.now(KST).replace(tzinfo=None)


class NotificationService:
    """알림 및 보고서 관리 서비스"""
    
    def __init__(self, db_session: Session):
        self.db = db_session

    async def list_active_alerts(self, cluster: str = "nks-cluster") -> List[Dict[str, Any]]:
        """
        활성 알림 목록 조회 (nks-prometheus 기반, persist-on-first-trigger)

        - 카테고리: CPU, Memory, Disk, Network
        - 규칙 예시:
          CPU: utilization>80/90, iowait>5/10
          Memory: usage>80/90, swap>0
          Disk: root usage>85/95, IO saturation>0.8, readonly==1
          Network: rx_errors>0/s, rx_drops>0/s, high throughput(>~50MB/s)
        - 동작: 조건이 참이면 DB(Notification)에 status=firing으로 1회 저장 후, 사용자가 resolve할 때까지 유지
        - 반환: DB의 firing 알림을 시간순으로 반환
        """
        alerts: List[Dict[str, Any]] = []

        try:
            # Upsert helper: persist alert if triggered
            def _upsert_alert(alert: Dict[str, Any]) -> None:
                try:
                    notif = self.db.query(Notification).filter(Notification.id == alert["id"]).first()
                    if notif is None:
                        notif = Notification(
                            id=alert["id"],
                            title=alert["title"],
                            description=alert.get("description"),
                            severity=alert.get("severity", "info"),
                            source=alert.get("source", "Prometheus"),
                            status="firing",
                            labels=None,
                            created_at=get_kst_now(),
                        )
                        self.db.add(notif)
                    else:
                        notif.title = alert["title"]
                        notif.description = alert.get("description")
                        notif.severity = alert.get("severity", notif.severity)
                        notif.source = alert.get("source", notif.source)
                        notif.status = "firing"
                    self.db.flush()
                except Exception as e:
                    logger.error("alert_upsert_failed", error=str(e), alert_id=alert.get("id"))
            # Build PromQL (align with monitoring.py)
            q_cpu_util = f'100 - (avg(rate(node_cpu_seconds_total{{cluster="{cluster}", mode="idle"}}[1m])) by (instance) * 100)'
            q_cpu_iowait = f'avg(rate(node_cpu_seconds_total{{cluster="{cluster}", mode="iowait"}}[1m])) by (instance) * 100'

            q_mem_usage = f'(1 - (node_memory_MemAvailable_bytes{{cluster="{cluster}"}} / node_memory_MemTotal_bytes{{cluster="{cluster}"}})) * 100'
            q_swap_used = f'node_memory_SwapTotal_bytes{{cluster="{cluster}"}} - node_memory_SwapFree_bytes{{cluster="{cluster}"}}'

            q_disk_root_usage = f'(1 - (node_filesystem_free_bytes{{cluster="{cluster}", mountpoint="/", fstype!="rootfs"}} / node_filesystem_size_bytes{{cluster="{cluster}", mountpoint="/", fstype!="rootfs"}})) * 100'
            q_disk_io_sat = f'rate(node_disk_io_time_seconds_total{{cluster="{cluster}"}}[1m])'
            q_disk_readonly = f'node_filesystem_readonly{{cluster="{cluster}", mountpoint="/"}}'

            q_net_rx_bps = f'rate(node_network_receive_bytes_total{{cluster="{cluster}", device="eth0"}}[1m])'
            q_net_tx_bps = f'rate(node_network_transmit_bytes_total{{cluster="{cluster}", device="eth0"}}[1m])'
            q_net_rx_errs = f'rate(node_network_receive_errs_total{{cluster="{cluster}"}}[1m])'
            q_net_rx_drops = f'rate(node_network_receive_drop_total{{cluster="{cluster}"}}[1m])'

            import asyncio
            async def _q(expr: str):
                return await query_prometheus(PromQuery(query=expr))

            (cpu_util_res, cpu_iowait_res,
             mem_usage_res, swap_used_res,
             disk_root_res, disk_io_sat_res, disk_ro_res,
             net_rx_res, net_tx_res, net_rx_errs_res, net_rx_drops_res) = await asyncio.gather(
                _q(q_cpu_util), _q(q_cpu_iowait),
                _q(q_mem_usage), _q(q_swap_used),
                _q(q_disk_root_usage), _q(q_disk_io_sat), _q(q_disk_readonly),
                _q(q_net_rx_bps), _q(q_net_tx_bps), _q(q_net_rx_errs), _q(q_net_rx_drops),
                return_exceptions=False
            )

            # Helper to extract value
            def _iter(res):
                return (res or {}).get("data", {}).get("result", [])

            # CPU alerts (2~3 rules)
            for r in _iter(cpu_util_res):
                try:
                    inst = r.get("metric", {}).get("instance")
                    val = float(r.get("value", [None, "0"]) [1])
                    if val > 80:
                        alert = {
                            "id": f"cpu-high-{inst}",
                            "title": "High CPU Utilization",
                            "description": f"Node {inst} CPU usage {val:.2f}%",
                            "severity": "critical" if val > 90 else "warning",
                            "status": "firing",
                            "timestamp": datetime.now(KST).isoformat(),
                            "source": "Prometheus",
                        }
                        alerts.append(alert)
                        _upsert_alert(alert)
                except Exception:
                    continue

            for r in _iter(cpu_iowait_res):
                try:
                    inst = r.get("metric", {}).get("instance")
                    val = float(r.get("value", [None, "0"]) [1])
                    if val > 5:
                        alert = {
                            "id": f"cpu-iowait-{inst}",
                            "title": "High CPU I/O wait",
                            "description": f"Node {inst} CPU iowait {val:.2f}%",
                            "severity": "critical" if val > 10 else "warning",
                            "status": "firing",
                            "timestamp": datetime.now(KST).isoformat(),
                            "source": "Prometheus",
                        }
                        alerts.append(alert)
                        _upsert_alert(alert)
                except Exception:
                    continue

            # Memory alerts
            for r in _iter(mem_usage_res):
                try:
                    inst = r.get("metric", {}).get("instance")
                    val = float(r.get("value", [None, "0"]) [1])
                    if val > 80:
                        alert = {
                            "id": f"mem-high-{inst}",
                            "title": "High Memory Usage",
                            "description": f"Node {inst} memory usage {val:.2f}%",
                            "severity": "critical" if val > 90 else "warning",
                            "status": "firing",
                            "timestamp": datetime.now(KST).isoformat(),
                            "source": "Prometheus",
                        }
                        alerts.append(alert)
                        _upsert_alert(alert)
                except Exception:
                    continue

            for r in _iter(swap_used_res):
                try:
                    inst = r.get("metric", {}).get("instance")
                    val = float(r.get("value", [None, "0"]) [1])
                    if val > 0:
                        alert = {
                            "id": f"mem-swap-{inst}",
                            "title": "Swap In Use",
                            "description": f"Node {inst} swap in use",
                            "severity": "warning",
                            "status": "firing",
                            "timestamp": datetime.now(KST).isoformat(),
                            "source": "Prometheus",
                        }
                        alerts.append(alert)
                        _upsert_alert(alert)
                except Exception:
                    continue

            # Disk alerts
            for r in _iter(disk_root_res):
                try:
                    inst = r.get("metric", {}).get("instance")
                    val = float(r.get("value", [None, "0"]) [1])
                    if val > 85:
                        alert = {
                            "id": f"disk-root-{inst}",
                            "title": "High Disk Usage (/) ",
                            "description": f"Node {inst} root usage {val:.2f}%",
                            "severity": "critical" if val > 95 else "warning",
                            "status": "firing",
                            "timestamp": datetime.now(KST).isoformat(),
                            "source": "Prometheus",
                        }
                        alerts.append(alert)
                        _upsert_alert(alert)
                except Exception:
                    continue

            # IO saturation: use max per instance
            max_io: Dict[str, float] = {}
            for r in _iter(disk_io_sat_res):
                try:
                    inst = r.get("metric", {}).get("instance")
                    val = float(r.get("value", [None, "0"]) [1])
                    max_io[inst] = max(val, max_io.get(inst, 0.0))
                except Exception:
                    continue
            for inst, val in max_io.items():
                if val > 0.8:
                    alert = {
                        "id": f"disk-io-{inst}",
                        "title": "High Disk IO Saturation",
                        "description": f"Node {inst} IO saturation {val:.2f}",
                        "severity": "warning",
                        "status": "firing",
                        "timestamp": datetime.now(KST).isoformat(),
                        "source": "Prometheus",
                    }
                    alerts.append(alert)
                    _upsert_alert(alert)

            for r in _iter(disk_ro_res):
                try:
                    inst = r.get("metric", {}).get("instance")
                    val = float(r.get("value", [None, "0"]) [1])
                    if val > 0:
                        alert = {
                            "id": f"disk-readonly-{inst}",
                            "title": "Filesystem Readonly",
                            "description": f"Node {inst} filesystem is readonly",
                            "severity": "critical",
                            "status": "firing",
                            "timestamp": datetime.now(KST).isoformat(),
                            "source": "Prometheus",
                        }
                        alerts.append(alert)
                        _upsert_alert(alert)
                except Exception:
                    continue

            # Network alerts
            for r in _iter(net_rx_errs_res):
                try:
                    inst = r.get("metric", {}).get("instance")
                    val = float(r.get("value", [None, "0"]) [1])
                    if val > 0:
                        alert = {
                            "id": f"net-rx-errors-{inst}",
                            "title": "Network RX Errors",
                            "description": f"Node {inst} rx errors {val:.2f}/s",
                            "severity": "warning",
                            "status": "firing",
                            "timestamp": datetime.now(KST).isoformat(),
                            "source": "Prometheus",
                        }
                        alerts.append(alert)
                        _upsert_alert(alert)
                except Exception:
                    continue

            for r in _iter(net_rx_drops_res):
                try:
                    inst = r.get("metric", {}).get("instance")
                    val = float(r.get("value", [None, "0"]) [1])
                    if val > 0:
                        alert = {
                            "id": f"net-rx-drops-{inst}",
                            "title": "Network RX Drops",
                            "description": f"Node {inst} rx drops {val:.2f}/s",
                            "severity": "warning",
                            "status": "firing",
                            "timestamp": datetime.now(KST).isoformat(),
                            "source": "Prometheus",
                        }
                        alerts.append(alert)
                        _upsert_alert(alert)
                except Exception:
                    continue

            # High throughput (optional thresholds)
            HIGH_BPS = 50 * 1024 * 1024  # ~50 MB/s
            for r in _iter(net_rx_res):
                try:
                    inst = r.get("metric", {}).get("instance")
                    val = float(r.get("value", [None, "0"]) [1])
                    if val > HIGH_BPS:
                        alert = {
                            "id": f"net-rx-high-{inst}",
                            "title": "High Inbound Traffic",
                            "description": f"Node {inst} inbound {val/1024/1024:.2f} MB/s",
                            "severity": "warning",
                            "status": "firing",
                            "timestamp": datetime.now(KST).isoformat(),
                            "source": "Prometheus",
                        }
                        alerts.append(alert)
                        _upsert_alert(alert)
                except Exception:
                    continue

            for r in _iter(net_tx_res):
                try:
                    inst = r.get("metric", {}).get("instance")
                    val = float(r.get("value", [None, "0"]) [1])
                    if val > HIGH_BPS:
                        alert = {
                            "id": f"net-tx-high-{inst}",
                            "title": "High Outbound Traffic",
                            "description": f"Node {inst} outbound {val/1024/1024:.2f} MB/s",
                            "severity": "warning",
                            "status": "firing",
                            "timestamp": datetime.now(KST).isoformat(),
                            "source": "Prometheus",
                        }
                        alerts.append(alert)
                        _upsert_alert(alert)
                except Exception:
                    continue

            # commit upserts
            try:
                self.db.commit()
            except Exception as e:
                logger.error("alert_commit_failed", error=str(e))
                self.db.rollback()

            # always return DB firing alerts ordered by created_at desc
            notifications = self.db.query(Notification).filter(
                Notification.status == "firing"
            ).order_by(desc(Notification.created_at)).limit(200).all()

            return [
                {
                    "id": n.id,
                    "title": n.title,
                    "description": n.description or "",
                    "severity": n.severity,
                    "status": n.status,
                    "timestamp": n.created_at.isoformat() if n.created_at else None,
                    "source": n.source or "System",
                }
                for n in notifications
            ]

        except Exception as e:
            logger.error("failed_to_list_alerts", error=str(e))
            return []

    async def generate_report_from_current_state(
        self,
        notification: Dict[str, Any],
        cluster: str = "nks-cluster"
    ) -> Dict[str, Any]:
        """
        현재 모니터링 상태를 기반으로 스냅샷 보고서 생성
        
        Args:
            notification: 알림 정보 (id, title, description, severity, source)
            cluster: 클러스터 이름
            
        Returns:
            생성된 보고서 정보
        """
        try:
            # 모니터링 상세 지표 조회 (API 엔드포인트 함수 직접 호출)
            from ..api.v1.monitoring import get_monitoring_details
            monitoring_data = await get_monitoring_details(cluster)
            
            # 스냅샷 데이터 구성
            snapshot = {
                "cluster": cluster,
                "generated_at": datetime.now(KST).isoformat(),
                "alert": {
                    "id": notification.get("id", ""),
                    "title": notification.get("title", ""),
                    "severity": notification.get("severity", "info"),
                    "source": notification.get("source", "System"),
                    "description": notification.get("description", "")
                },
                "nodes": monitoring_data.get("nodes", []),
                "thresholds": {
                    "cpu_pct": 80,
                    "mem_pct": 80,
                    "disk_root_pct": 85,
                    "iowait_pct": 5,
                    "io_sat": 0.8
                }
            }
            
            # 보고서 요약 생성
            node_count = len(monitoring_data.get("nodes", []))
            summary = f"Cluster: {cluster}, Nodes: {node_count}, Alert: {notification.get('title', 'Unknown')}"
            
            # Notification이 DB에 없으면 생성
            notification_id = notification.get("id", "")
            if notification_id:
                existing_notif = self.db.query(Notification).filter(
                    Notification.id == notification_id
                ).first()
                
                if not existing_notif:
                    new_notif = Notification(
                        id=notification_id,
                        title=notification.get("title", "Unknown Alert"),
                        description=notification.get("description", ""),
                        severity=notification.get("severity", "info"),
                        source=notification.get("source", "System"),
                        status=notification.get("status", "firing"),
                        labels=notification.get("labels")
                    )
                    self.db.add(new_notif)
                    self.db.commit()
            
            # NotificationReport 생성
            report_id = f"report-{uuid.uuid4().hex[:12]}"
            report = NotificationReport(
                id=report_id,
                notification_id=notification_id,
                cluster=cluster,
                summary=summary,
                snapshot_json=snapshot
            )
            
            self.db.add(report)
            self.db.commit()
            self.db.refresh(report)
            
            logger.info(
                "notification_report_created",
                report_id=report_id,
                notification_id=notification_id,
                cluster=cluster
            )
            
            return {
                "report_id": report_id,
                "notification_id": notification_id,
                "created_at": report.created_at.isoformat() if report.created_at else None,
                "summary": summary,
                "snapshot": snapshot
            }
            
        except Exception as e:
            logger.error(
                "failed_to_generate_report",
                error=str(e),
                notification_id=notification.get("id", "")
            )
            self.db.rollback()
            raise

    def get_report(self, report_id: str) -> Optional[Dict[str, Any]]:
        """보고서 조회"""
        try:
            report = self.db.query(NotificationReport).filter(
                NotificationReport.id == report_id
            ).first()
            
            if not report:
                return None
            
            return {
                "report_id": report.id,
                "notification_id": report.notification_id,
                "cluster": report.cluster,
                "summary": report.summary,
                "snapshot": report.snapshot_json,
                "created_at": report.created_at.isoformat() if report.created_at else None
            }
        except Exception as e:
            logger.error("failed_to_get_report", error=str(e), report_id=report_id)
            return None

    def list_reports(self, notification_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        """알림의 보고서 목록 조회"""
        try:
            reports = self.db.query(NotificationReport).filter(
                NotificationReport.notification_id == notification_id
            ).order_by(desc(NotificationReport.created_at)).limit(limit).all()
            
            return [
                {
                    "report_id": r.id,
                    "notification_id": r.notification_id,
                    "cluster": r.cluster,
                    "summary": r.summary,
                    "created_at": r.created_at.isoformat() if r.created_at else None
                }
                for r in reports
            ]
        except Exception as e:
            logger.error(
                "failed_to_list_reports",
                error=str(e),
                notification_id=notification_id
            )
            return []

    def resolve_alert(self, alert_id: str) -> bool:
        """알림을 해결(resolved) 상태로 변경합니다. 존재하지 않으면 False 반환."""
        try:
            notif = self.db.query(Notification).filter(Notification.id == alert_id).first()
            if not notif:
                return False
            notif.status = "resolved"
            notif.resolved_at = get_kst_now()
            self.db.add(notif)
            self.db.commit()
            return True
        except Exception as e:
            logger.error("failed_to_resolve_alert", error=str(e), alert_id=alert_id)
            self.db.rollback()
            return False

    def seed_example_alerts(self) -> int:
        """예시 알림 4개를 생성합니다. 이미 존재하면 건너뜁니다.

        Returns:
            int: 생성된(또는 이미 존재하여 유지된) 총 개수
        """
        # 기존 파드 관련 데모 알림 정리
        try:
            self.db.query(Notification).filter(Notification.id.like("restart-%")).delete(synchronize_session=False)
            self.db.commit()
        except Exception:
            self.db.rollback()

        examples = [
            {
                "id": "cpu-demo-001",
                "title": "높은 CPU 사용률",
                "description": "api-service pod가 90% CPU 사용",
                "severity": "warning",
                "source": "Prometheus",
                "status": "firing",
            },
            {
                "id": "mem-demo-002",
                "title": "메모리 부족",
                "description": "node k8s-worker-01 메모리 사용률이 86%",
                "severity": "critical",
                "source": "Prometheus",
                "status": "firing",
            },
            {
                "id": "disk-demo-003",
                "title": "디스크 사용량 높음 (/)",
                "description": "node k8s-worker-01 root filesystem usage 92%",
                "severity": "warning",
                "source": "Prometheus",
                "status": "firing",
            },
            {
                "id": "deploy-demo-004",
                "title": "배포 완료",
                "description": "frontend-app v2.1.0 배포 성공",
                "severity": "info",
                "source": "CI/CD",
                "status": "resolved",
            },
        ]

        created = 0
        try:
            for e in examples:
                existing = self.db.query(Notification).filter(Notification.id == e["id"]).first()
                if existing:
                    # 상태/내용 최신화만 수행
                    existing.title = e["title"]
                    existing.description = e["description"]
                    existing.severity = e["severity"]
                    existing.source = e["source"]
                    existing.status = e["status"]
                else:
                    self.db.add(
                        Notification(
                            id=e["id"],
                            title=e["title"],
                            description=e["description"],
                            severity=e["severity"],
                            source=e["source"],
                            status=e["status"],
                            created_at=get_kst_now(),
                        )
                    )
                    created += 1
            self.db.commit()
            return created
        except Exception as e:
            logger.error("seed_example_alerts_failed", error=str(e))
            self.db.rollback()
            return created

    async def seed_examples_from_current_metrics(self, cluster: str = "nks-cluster", per_rule: int = 1, max_total: int = 8) -> int:
        """현재 Prometheus 데이터에서 관측된 instance/값을 이용해 모든 규칙 유형의 데모 알림을 생성합니다.

        Args:
            cluster: 대상 클러스터
            per_rule: 규칙 당 최대 몇 개의 인스턴스에 대해 생성할지

        Returns:
            생성(또는 갱신)된 알림 개수
        """
        created = 0
        candidates: List[Dict[str, Any]] = []

        # Reuse same PromQL set as list_active_alerts
        q_cpu_util = f'100 - (avg(rate(node_cpu_seconds_total{{cluster="{cluster}", mode="idle"}}[1m])) by (instance) * 100)'
        q_cpu_iowait = f'avg(rate(node_cpu_seconds_total{{cluster="{cluster}", mode="iowait"}}[1m])) by (instance) * 100'
        q_mem_usage = f'(1 - (node_memory_MemAvailable_bytes{{cluster="{cluster}"}} / node_memory_MemTotal_bytes{{cluster="{cluster}"}})) * 100'
        q_swap_used = f'node_memory_SwapTotal_bytes{{cluster="{cluster}"}} - node_memory_SwapFree_bytes{{cluster="{cluster}"}}'
        q_disk_root_usage = f'(1 - (node_filesystem_free_bytes{{cluster="{cluster}", mountpoint="/", fstype!="rootfs"}} / node_filesystem_size_bytes{{cluster="{cluster}", mountpoint="/", fstype!="rootfs"}})) * 100'
        q_disk_io_sat = f'rate(node_disk_io_time_seconds_total{{cluster="{cluster}"}}[1m])'
        q_disk_readonly = f'node_filesystem_readonly{{cluster="{cluster}", mountpoint="/"}}'
        q_net_rx_bps = f'rate(node_network_receive_bytes_total{{cluster="{cluster}", device="eth0"}}[1m])'
        q_net_tx_bps = f'rate(node_network_transmit_bytes_total{{cluster="{cluster}", device="eth0"}}[1m])'
        q_net_rx_errs = f'rate(node_network_receive_errs_total{{cluster="{cluster}"}}[1m])'
        q_net_rx_drops = f'rate(node_network_receive_drop_total{{cluster="{cluster}"}}[1m])'

        import asyncio
        async def _q(expr: str):
            return await query_prometheus(PromQuery(query=expr))

        (cpu_util_res, cpu_iowait_res,
         mem_usage_res, swap_used_res,
         disk_root_res, disk_io_sat_res, disk_ro_res,
         net_rx_res, net_tx_res, net_rx_errs_res, net_rx_drops_res) = await asyncio.gather(
            _q(q_cpu_util), _q(q_cpu_iowait),
            _q(q_mem_usage), _q(q_swap_used),
            _q(q_disk_root_usage), _q(q_disk_io_sat), _q(q_disk_readonly),
            _q(q_net_rx_bps), _q(q_net_tx_bps), _q(q_net_rx_errs), _q(q_net_rx_drops),
            return_exceptions=False
        )

        def _iter(res):
            return (res or {}).get("data", {}).get("result", [])

        def _save(alert: Dict[str, Any]):
            nonlocal created
            try:
                existing = self.db.query(Notification).filter(Notification.id == alert["id"]).first()
                if existing:
                    existing.title = alert["title"]
                    existing.description = alert.get("description")
                    existing.severity = alert.get("severity", existing.severity)
                    existing.source = alert.get("source", existing.source)
                    existing.status = alert.get("status", existing.status)
                else:
                    self.db.add(
                        Notification(
                            id=alert["id"],
                            title=alert["title"],
                            description=alert.get("description"),
                            severity=alert.get("severity", "info"),
                            source=alert.get("source", "Prometheus"),
                            status=alert.get("status", "firing"),
                            created_at=get_kst_now(),
                        )
                    )
                    created += 1
            except Exception as e:
                logger.error("seed_from_current_save_failed", error=str(e), alert_id=alert.get("id"))

        now = datetime.now(KST).isoformat()
        # CPU examples
        for r in _iter(cpu_util_res)[:per_rule]:
            inst = r.get("metric", {}).get("instance")
            val = float(r.get("value", [None, "0"]) [1])
            candidates.append({
                "id": f"demo-cpu-high-{inst}",
                "title": "[Demo] High CPU Utilization",
                "description": f"Node {inst} CPU usage {val:.2f}%",
                "severity": "warning",
                "source": "Prometheus",
                "status": "firing",
                "score": 100 + val,
            })
        for r in _iter(cpu_iowait_res)[:per_rule]:
            inst = r.get("metric", {}).get("instance")
            val = float(r.get("value", [None, "0"]) [1])
            candidates.append({
                "id": f"demo-cpu-iowait-{inst}",
                "title": "[Demo] High CPU I/O wait",
                "description": f"Node {inst} iowait {val:.2f}%",
                "severity": "warning",
                "source": "Prometheus",
                "status": "firing",
                "score": 80 + val,
            })

        # Memory examples
        for r in _iter(mem_usage_res)[:per_rule]:
            inst = r.get("metric", {}).get("instance")
            val = float(r.get("value", [None, "0"]) [1])
            candidates.append({
                "id": f"demo-mem-high-{inst}",
                "title": "[Demo] High Memory Usage",
                "description": f"Node {inst} memory usage {val:.2f}%",
                "severity": "warning",
                "source": "Prometheus",
                "status": "firing",
                "score": 100 + val,
            })
        for r in _iter(swap_used_res)[:per_rule]:
            inst = r.get("metric", {}).get("instance")
            val = float(r.get("value", [None, "0"]) [1])
            candidates.append({
                "id": f"demo-mem-swap-{inst}",
                "title": "[Demo] Swap In Use",
                "description": f"Node {inst} swap in use ({val:.0f} bytes)",
                "severity": "warning",
                "source": "Prometheus",
                "status": "firing",
                "score": 60 + (1 if val>0 else 0),
            })

        # Disk examples
        for r in _iter(disk_root_res)[:per_rule]:
            inst = r.get("metric", {}).get("instance")
            val = float(r.get("value", [None, "0"]) [1])
            candidates.append({
                "id": f"demo-disk-root-{inst}",
                "title": "[Demo] High Disk Usage (/) ",
                "description": f"Node {inst} root usage {val:.2f}%",
                "severity": "warning",
                "source": "Prometheus",
                "status": "firing",
                "score": 100 + val,
            })
        for r in _iter(disk_io_sat_res)[:per_rule]:
            inst = r.get("metric", {}).get("instance")
            val = float(r.get("value", [None, "0"]) [1])
            candidates.append({
                "id": f"demo-disk-io-{inst}",
                "title": "[Demo] High Disk IO Saturation",
                "description": f"Node {inst} IO saturation {val:.2f}",
                "severity": "warning",
                "source": "Prometheus",
                "status": "firing",
                "score": 70 + val * 100,
            })
        for r in _iter(disk_ro_res)[:per_rule]:
            inst = r.get("metric", {}).get("instance")
            val = float(r.get("value", [None, "0"]) [1])
            candidates.append({
                "id": f"demo-disk-readonly-{inst}",
                "title": "[Demo] Filesystem Readonly",
                "description": f"Node {inst} filesystem readonly={val}",
                "severity": "critical",
                "source": "Prometheus",
                "status": "firing",
                "score": 200,
            })

        # Network examples
        for r in _iter(net_rx_errs_res)[:per_rule]:
            inst = r.get("metric", {}).get("instance")
            val = float(r.get("value", [None, "0"]) [1])
            candidates.append({
                "id": f"demo-net-rx-errors-{inst}",
                "title": "[Demo] Network RX Errors",
                "description": f"Node {inst} rx errors {val:.2f}/s",
                "severity": "warning",
                "source": "Prometheus",
                "status": "firing",
                "score": 50 + val,
            })
        for r in _iter(net_rx_drops_res)[:per_rule]:
            inst = r.get("metric", {}).get("instance")
            val = float(r.get("value", [None, "0"]) [1])
            candidates.append({
                "id": f"demo-net-rx-drops-{inst}",
                "title": "[Demo] Network RX Drops",
                "description": f"Node {inst} rx drops {val:.2f}/s",
                "severity": "warning",
                "source": "Prometheus",
                "status": "firing",
                "score": 50 + val,
            })
        HIGH_BPS = 50 * 1024 * 1024
        for r in _iter(net_rx_res)[:per_rule]:
            inst = r.get("metric", {}).get("instance")
            val = float(r.get("value", [None, "0"]) [1])
            candidates.append({
                "id": f"demo-net-rx-high-{inst}",
                "title": "[Demo] High Inbound Traffic",
                "description": f"Node {inst} inbound {val/1024/1024:.2f} MB/s",
                "severity": "warning" if val > HIGH_BPS else "info",
                "source": "Prometheus",
                "status": "firing",
                "score": 40 + val/1024/1024,
            })
        for r in _iter(net_tx_res)[:per_rule]:
            inst = r.get("metric", {}).get("instance")
            val = float(r.get("value", [None, "0"]) [1])
            candidates.append({
                "id": f"demo-net-tx-high-{inst}",
                "title": "[Demo] High Outbound Traffic",
                "description": f"Node {inst} outbound {val/1024/1024:.2f} MB/s",
                "severity": "warning" if val > HIGH_BPS else "info",
                "source": "Prometheus",
                "status": "firing",
                "score": 40 + val/1024/1024,
            })

        # Pick top-N by score, unique by id
        seen: set[str] = set()
        selected: List[Dict[str, Any]] = []
        for a in sorted(candidates, key=lambda x: x.get("score", 0), reverse=True):
            if a["id"] in seen:
                continue
            selected.append(a)
            seen.add(a["id"])
            if len(selected) >= max_total:
                break

        for a in selected:
            _save(a)

        try:
            self.db.commit()
        except Exception as e:
            logger.error("seed_from_current_commit_failed", error=str(e))
            self.db.rollback()
        return created

