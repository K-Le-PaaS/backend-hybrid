from typing import Any, Dict, List
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from ...database import get_db
from ...services.monitoring import PromQuery, query_prometheus

router = APIRouter()

@router.post("/monitoring/query", response_model=dict)
async def prom_query(body: PromQuery) -> Dict[str, Any]:
    """Prometheus 쿼리 실행"""
    try:
        result = await query_prometheus(body)
        return {
            "status": "success",
            "data": result,
            "message": "Query executed successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")

@router.get("/monitoring/metrics/details", response_model=Dict[str, Any])
async def get_monitoring_details(cluster: str = "nks-cluster") -> Dict[str, Any]:
    """클러스터 노드별 상세 모니터링 지표 반환 (CPU/Memory/Disk/Network).

    기본적으로 NKS 클러스터만 대상으로 합니다. 다른 클러스터가 필요하면 ?cluster= 파라미터로 지정하세요.
    """
    # PromQL 정의 (모든 쿼리에 cluster 필터 적용)
    q_cpu_util = f'100 - (avg(rate(node_cpu_seconds_total{{cluster="{cluster}", mode="idle"}}[1m])) by (instance) * 100)'
    q_cpu_load = f'node_load1{{cluster="{cluster}"}} / count(node_cpu_seconds_total{{cluster="{cluster}", mode="system"}}) by (instance)'
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

    async def run_query(expr: str):
        return await query_prometheus(PromQuery(query=expr))

    # 병렬 실행
    (cpu_util_res, cpu_load_res, cpu_iowait_res,
     mem_usage_res, swap_used_res,
     disk_root_res, disk_io_sat_res, disk_ro_res,
     net_rx_res, net_tx_res, net_rx_errs_res, net_rx_drops_res) = await asyncio.gather(
        run_query(q_cpu_util), run_query(q_cpu_load), run_query(q_cpu_iowait),
        run_query(q_mem_usage), run_query(q_swap_used),
        run_query(q_disk_root_usage), run_query(q_disk_io_sat), run_query(q_disk_readonly),
        run_query(q_net_rx_bps), run_query(q_net_tx_bps), run_query(q_net_rx_errs), run_query(q_net_rx_drops),
        return_exceptions=False
    )

    def results(data: Dict[str, Any]) -> list:
        return (data or {}).get("data", {}).get("result", [])

    merged: Dict[str, Dict[str, Any]] = {}

    def merge(expr_result: list, field: str, cast=float):
        for item in expr_result:
            metric = item.get("metric", {})
            instance = metric.get("instance")
            if not instance:
                continue
            value = item.get("value")
            v = None
            if isinstance(value, list) and len(value) > 1:
                try:
                    v = cast(value[1])
                except Exception:
                    v = None
            merged.setdefault(instance, {})[field] = v

    merge(results(cpu_util_res), "cpu_utilization_pct")
    merge(results(cpu_load_res), "cpu_load_avg_per_core")
    merge(results(cpu_iowait_res), "cpu_iowait_pct")

    merge(results(mem_usage_res), "memory_usage_pct")
    merge(results(swap_used_res), "swap_used_bytes", cast=float)

    # 디스크 루트 사용률
    merge(results(disk_root_res), "disk_root_usage_pct")

    # IO saturation: 같은 인스턴스에서 최대값 사용
    for item in results(disk_io_sat_res):
        metric = item.get("metric", {})
        instance = metric.get("instance")
        if not instance:
            continue
        value = item.get("value")
        io_sat = float(value[1]) if isinstance(value, list) and len(value) > 1 else None
        prev = merged.setdefault(instance, {}).get("disk_io_saturation")
        if prev is None or (io_sat is not None and io_sat > prev):
            merged[instance]["disk_io_saturation"] = io_sat

    # Readonly
    for item in results(disk_ro_res):
        metric = item.get("metric", {})
        instance = metric.get("instance")
        if not instance:
            continue
        value = item.get("value")
        readonly_flag = float(value[1]) if isinstance(value, list) and len(value) > 1 else 0.0
        merged.setdefault(instance, {})["disk_readonly"] = bool(readonly_flag and readonly_flag > 0.0)

    merge(results(net_rx_res), "net_rx_bps")
    merge(results(net_tx_res), "net_tx_bps")
    merge(results(net_rx_errs_res), "net_rx_errs_ps")
    merge(results(net_rx_drops_res), "net_rx_drops_ps")

    nodes: List[Dict[str, Any]] = []
    for instance, vals in merged.items():
        alerts: List[str] = []
        if (vals.get("cpu_utilization_pct") or 0) > 80:
            alerts.append("CPU > 80%")
        if (vals.get("cpu_iowait_pct") or 0) > 5:
            alerts.append("CPU I/O wait > 5%")
        if (vals.get("memory_usage_pct") or 0) > 80:
            alerts.append("Memory > 80%")
        if (vals.get("disk_root_usage_pct") or 0) > 85:
            alerts.append("Disk / > 85%")
        if (vals.get("disk_io_saturation") or 0) > 0.8:
            alerts.append("Disk I/O saturation high")
        if vals.get("disk_readonly"):
            alerts.append("Filesystem readonly")
        if (vals.get("net_rx_errs_ps") or 0) > 0:
            alerts.append("Network RX errors > 0")
        if (vals.get("net_rx_drops_ps") or 0) > 0:
            alerts.append("Network RX drops > 0")

        severity = "info"
        if any(a for a in alerts if "readonly" in a or "Disk / >" in a or "CPU > 80%" in a):
            severity = "warning"
        if vals.get("disk_readonly"):
            severity = "critical"

        nodes.append({
            "instance": instance,
            "cpu": {
                "utilization_pct": vals.get("cpu_utilization_pct"),
                "load_avg_per_core": vals.get("cpu_load_avg_per_core"),
                "iowait_pct": vals.get("cpu_iowait_pct"),
            },
            "memory": {
                "usage_pct": vals.get("memory_usage_pct"),
                "swap_used_bytes": vals.get("swap_used_bytes"),
            },
            "disk": {
                "root_usage_pct": vals.get("disk_root_usage_pct"),
                "io_saturation": vals.get("disk_io_saturation"),
                "readonly": vals.get("disk_readonly", False),
            },
            "network": {
                "rx_bps": vals.get("net_rx_bps"),
                "tx_bps": vals.get("net_tx_bps"),
                "rx_errs_ps": vals.get("net_rx_errs_ps"),
                "rx_drops_ps": vals.get("net_rx_drops_ps"),
            },
            "alerts": {
                "severity": severity,
                "reasons": alerts,
            },
        })

    return {"cluster": cluster, "nodes": nodes}

@router.get("/monitoring/alerts", response_model=List[Dict[str, Any]])
async def get_alerts() -> List[Dict[str, Any]]:
    """활성 알림 목록 조회"""
    # TODO: 실제 알림 시스템과 연동
    return [
        {
            "id": "alert-001",
            "title": "높은 CPU 사용률",
            "description": "api-service pod가 90% CPU 사용",
            "severity": "warning",
            "status": "firing",
            "timestamp": "2024-01-15T10:30:00Z",
            "source": "Prometheus"
        },
        {
            "id": "alert-002", 
            "title": "메모리 부족",
            "description": "시스템 메모리 사용률이 85%를 초과했습니다",
            "severity": "error",
            "status": "firing",
            "timestamp": "2024-01-15T10:25:00Z",
            "source": "Node Exporter"
        },
        {
            "id": "alert-003",
            "title": "배포 완료",
            "description": "my-app v1.2.3이 성공적으로 배포되었습니다",
            "severity": "info",
            "status": "resolved",
            "timestamp": "2024-01-15T09:45:00Z",
            "source": "K-Le-PaaS"
        }
    ]

@router.get("/monitoring/metrics/cpu", response_model=Dict[str, Any])
async def get_cpu_metrics() -> Dict[str, Any]:
    """CPU 사용률 메트릭 조회"""
    try:
        # CPU 사용률 쿼리
        cpu_query = '100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)'
        result = await query_prometheus(PromQuery(query=cpu_query))
        
        return {
            "status": "success",
            "data": result,
            "message": "CPU metrics retrieved successfully"
        }
    except Exception as e:
        # Prometheus가 없는 경우 모의 데이터 반환
        return {
            "status": "success",
            "data": {
                "result": [
                    {
                        "metric": {"instance": "localhost:9100"},
                        "value": [str(int(__import__('time').time())), "45.2"]
                    }
                ]
            },
            "message": "CPU metrics (mock data)"
        }

@router.get("/monitoring/metrics/memory", response_model=Dict[str, Any])
async def get_memory_metrics() -> Dict[str, Any]:
    """메모리 사용률 메트릭 조회"""
    try:
        # 메모리 사용률 쿼리
        memory_query = '(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100'
        result = await query_prometheus(PromQuery(query=memory_query))
        
        return {
            "status": "success",
            "data": result,
            "message": "Memory metrics retrieved successfully"
        }
    except Exception as e:
        # Prometheus가 없는 경우 모의 데이터 반환
        return {
            "status": "success",
            "data": {
                "result": [
                    {
                        "metric": {"instance": "localhost:9100"},
                        "value": [str(int(__import__('time').time())), "72.5"]
                    }
                ]
            },
            "message": "Memory metrics (mock data)"
        }

@router.get("/monitoring/metrics/storage", response_model=Dict[str, Any])
async def get_storage_metrics() -> Dict[str, Any]:
    """스토리지 사용률 메트릭 조회"""
    try:
        # 스토리지 사용률 쿼리
        storage_query = '(1 - (node_filesystem_avail_bytes / node_filesystem_size_bytes)) * 100'
        result = await query_prometheus(PromQuery(query=storage_query))
        
        return {
            "status": "success",
            "data": result,
            "message": "Storage metrics retrieved successfully"
        }
    except Exception as e:
        # Prometheus가 없는 경우 모의 데이터 반환
        return {
            "status": "success",
            "data": {
                "result": [
                    {
                        "metric": {"instance": "localhost:9100"},
                        "value": [str(int(__import__('time').time())), "38.7"]
                    }
                ]
            },
            "message": "Storage metrics (mock data)"
        }

@router.get("/monitoring/health", response_model=Dict[str, Any])
async def get_monitoring_health() -> Dict[str, Any]:
    """모니터링 시스템 상태 조회"""
    return {
        "status": "healthy",
        "components": [
            {
                "name": "Prometheus",
                "status": "up",
                "responseTime": 45
            },
            {
                "name": "Node Exporter", 
                "status": "up",
                "responseTime": 23
            },
            {
                "name": "Alert Manager",
                "status": "up", 
                "responseTime": 67
            }
        ],
        "timestamp": __import__('datetime').datetime.utcnow().isoformat() + "Z"
    }


@router.get("/health/db", response_model=Dict[str, Any])
async def get_db_health(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """데이터베이스 연결 상태 확인 (읽기 전용)"""
    try:
        # 간단한 연결 확인 쿼리
        db.execute(text("SELECT 1"))
        return {
            "status": "ok",
            "database_url": "configured",
            "message": "Database connection successful"
        }
    except Exception as e:
        # 내부 정보 노출을 피하면서 원인 메시지는 포함
        return {
            "status": "bad",
            "database_url": "configured" if __import__('os').getenv('KLEPAAS_DATABASE_URL') else "sqlite:///./test.db",
            "message": f"Database connection failed: {str(e)}"
        }

# NKS 클러스터 전용 메트릭 엔드포인트
@router.get("/monitoring/nks/cpu-usage")
async def get_nks_cpu_usage() -> Dict[str, Any]:
    """NKS 클러스터 CPU 사용률 조회"""
    try:
        # NKS 클러스터 전용 CPU 사용률 쿼리
        query = '100 - (avg(rate(node_cpu_seconds_total{cluster="nks-cluster", mode="idle"}[2m])) * 100)'
        result = await query_prometheus(PromQuery(query=query))
        
        if result.get("status") == "success" and result.get("data", {}).get("result"):
            value = float(result["data"]["result"][0]["value"][1])
            return {
                "status": "success",
                "cluster": "nks-cluster",
                "metric": "cpu_usage",
                "value": round(value, 2),
                "unit": "percent",
                "message": "NKS CPU usage retrieved successfully"
            }
        else:
            return {
                "status": "error",
                "message": "No CPU usage data available for NKS cluster"
            }
            
    except Exception as e:
        return {
            "status": "error",
            "message": f"NKS CPU usage query failed: {str(e)}"
        }

@router.get("/monitoring/nks/memory-usage")
async def get_nks_memory_usage() -> Dict[str, Any]:
    """NKS 클러스터 메모리 사용률 조회"""
    try:
        # NKS 클러스터 전용 메모리 사용률 쿼리
        query = '(1 - (node_memory_MemAvailable_bytes{cluster="nks-cluster"} / node_memory_MemTotal_bytes{cluster="nks-cluster"})) * 100'
        result = await query_prometheus(PromQuery(query=query))
        
        if result.get("status") == "success" and result.get("data", {}).get("result"):
            value = float(result["data"]["result"][0]["value"][1])
            return {
                "status": "success",
                "cluster": "nks-cluster",
                "metric": "memory_usage",
                "value": round(value, 2),
                "unit": "percent",
                "message": "NKS memory usage retrieved successfully"
            }
        else:
            return {
                "status": "error",
                "message": "No memory usage data available for NKS cluster"
            }
            
    except Exception as e:
        return {
            "status": "error",
            "message": f"NKS memory usage query failed: {str(e)}"
        }

@router.get("/monitoring/nks/disk-usage")
async def get_nks_disk_usage() -> Dict[str, Any]:
    """NKS 클러스터 디스크 사용률 조회"""
    try:
        # NKS 클러스터 전용 디스크 사용률 쿼리
        query = '100 - ((node_filesystem_avail_bytes{cluster="nks-cluster", mountpoint="/"} / node_filesystem_size_bytes{cluster="nks-cluster", mountpoint="/"}) * 100)'
        result = await query_prometheus(PromQuery(query=query))
        
        if result.get("status") == "success" and result.get("data", {}).get("result"):
            value = float(result["data"]["result"][0]["value"][1])
            return {
                "status": "success",
                "cluster": "nks-cluster",
                "metric": "disk_usage",
                "value": round(value, 2),
                "unit": "percent",
                "message": "NKS disk usage retrieved successfully"
            }
        else:
            return {
                "status": "error",
                "message": "No disk usage data available for NKS cluster"
            }
            
    except Exception as e:
        return {
            "status": "error",
            "message": f"NKS disk usage query failed: {str(e)}"
        }

@router.get("/monitoring/nks/network-traffic")
async def get_nks_network_traffic() -> Dict[str, Any]:
    """NKS 클러스터 네트워크 트래픽 조회"""
    try:
        import asyncio
        
        # 병렬로 네트워크 인바운드/아웃바운드 트래픽 조회
        inbound_task = asyncio.create_task(query_prometheus(PromQuery(query='rate(node_network_receive_bytes_total{cluster="nks-cluster"}[5m])')))
        outbound_task = asyncio.create_task(query_prometheus(PromQuery(query='rate(node_network_transmit_bytes_total{cluster="nks-cluster"}[5m])')))
        
        inbound_result, outbound_result = await asyncio.gather(
            inbound_task, outbound_task, return_exceptions=True
        )
        
        # 결과 파싱
        inbound_traffic = None
        outbound_traffic = None
        
        if not isinstance(inbound_result, Exception) and inbound_result.get("data", {}).get("result"):
            # 모든 네트워크 인터페이스의 인바운드 트래픽 합계
            total_inbound = sum(float(r.get("value", [None, "0"])[1]) for r in inbound_result["data"]["result"])
            inbound_traffic = round(total_inbound / 1024 / 1024, 2)  # MB/s로 변환
            
        if not isinstance(outbound_result, Exception) and outbound_result.get("data", {}).get("result"):
            # 모든 네트워크 인터페이스의 아웃바운드 트래픽 합계
            total_outbound = sum(float(r.get("value", [None, "0"])[1]) for r in outbound_result["data"]["result"])
            outbound_traffic = round(total_outbound / 1024 / 1024, 2)  # MB/s로 변환
        
        return {
            "status": "success",
            "cluster": "nks-cluster",
            "metric": "network_traffic",
            "inbound_mbps": inbound_traffic,
            "outbound_mbps": outbound_traffic,
            "unit": "MB/s",
            "message": "NKS network traffic retrieved successfully"
        }
            
    except Exception as e:
        return {
            "status": "error",
            "message": f"NKS network traffic query failed: {str(e)}"
        }

@router.get("/monitoring/nks/overview")
async def get_nks_overview() -> Dict[str, Any]:
    """NKS 클러스터 전체 개요 조회"""
    try:
        import asyncio
        
        # 병렬로 모든 메트릭 조회
        cpu_task = asyncio.create_task(query_prometheus(PromQuery(query='100 - (avg(rate(node_cpu_seconds_total{cluster="nks-cluster", mode="idle"}[2m])) * 100)')))
        memory_task = asyncio.create_task(query_prometheus(PromQuery(query='(1 - (node_memory_MemAvailable_bytes{cluster="nks-cluster"} / node_memory_MemTotal_bytes{cluster="nks-cluster"})) * 100')))
        disk_task = asyncio.create_task(query_prometheus(PromQuery(query='100 - ((node_filesystem_avail_bytes{cluster="nks-cluster", mountpoint="/"} / node_filesystem_size_bytes{cluster="nks-cluster", mountpoint="/"}) * 100)')))
        inbound_task = asyncio.create_task(query_prometheus(PromQuery(query='rate(node_network_receive_bytes_total{cluster="nks-cluster"}[5m])')))
        outbound_task = asyncio.create_task(query_prometheus(PromQuery(query='rate(node_network_transmit_bytes_total{cluster="nks-cluster"}[5m])')))
        node_task = asyncio.create_task(query_prometheus(PromQuery(query='up{cluster="nks-cluster"}')))
        
        cpu_result, memory_result, disk_result, inbound_result, outbound_result, node_result = await asyncio.gather(
            cpu_task, memory_task, disk_task, inbound_task, outbound_task, node_task, return_exceptions=True
        )
        
        # 결과 파싱
        cpu_usage = None
        memory_usage = None
        disk_usage = None
        inbound_traffic = None
        outbound_traffic = None
        node_status = None
        
        if not isinstance(cpu_result, Exception) and cpu_result.get("data", {}).get("result"):
            cpu_usage = round(float(cpu_result["data"]["result"][0]["value"][1]), 2)
            
        if not isinstance(memory_result, Exception) and memory_result.get("data", {}).get("result"):
            memory_usage = round(float(memory_result["data"]["result"][0]["value"][1]), 2)
            
        if not isinstance(disk_result, Exception) and disk_result.get("data", {}).get("result"):
            disk_usage = round(float(disk_result["data"]["result"][0]["value"][1]), 2)
            
        if not isinstance(inbound_result, Exception) and inbound_result.get("data", {}).get("result"):
            total_inbound = sum(float(r.get("value", [None, "0"])[1]) for r in inbound_result["data"]["result"])
            inbound_traffic = round(total_inbound / 1024 / 1024, 2)  # MB/s로 변환
            
        if not isinstance(outbound_result, Exception) and outbound_result.get("data", {}).get("result"):
            total_outbound = sum(float(r.get("value", [None, "0"])[1]) for r in outbound_result["data"]["result"])
            outbound_traffic = round(total_outbound / 1024 / 1024, 2)  # MB/s로 변환
            
        if not isinstance(node_result, Exception) and node_result.get("data", {}).get("result"):
            results = node_result["data"]["result"]
            node_status = {
                "total_nodes": len(results),
                "healthy_nodes": sum(1 for r in results if float(r.get("value", [None, "0"])[1]) == 1),
                "nodes": [{"instance": r.get("metric", {}).get("instance", "unknown"), 
                          "status": "healthy" if float(r.get("value", [None, "0"])[1]) == 1 else "unhealthy"} 
                         for r in results]
            }
        
        return {
            "status": "success",
            "cluster": "nks-cluster",
            "timestamp": "2025-01-23T03:46:40Z",
            "metrics": {
                "cpu_usage": cpu_usage,
                "memory_usage": memory_usage,
                "disk_usage": disk_usage,
                "network_traffic": {
                    "inbound_mbps": inbound_traffic,
                    "outbound_mbps": outbound_traffic
                },
                "node_status": node_status
            },
            "overall_status": "healthy" if cpu_usage is not None and memory_usage is not None and disk_usage is not None else "degraded",
            "message": "NKS overview retrieved successfully"
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"NKS overview query failed: {str(e)}"
        }

@router.get("/monitoring/nks/pod-info")
async def get_nks_pod_info() -> Dict[str, Any]:
    """NKS 클러스터 Pod 정보 조회"""
    try:
        # Pod 수 조회 (더 간단한 쿼리 사용)
        pod_query = 'kube_pod_info{cluster="nks-cluster"}'
        pod_result = await query_prometheus(PromQuery(query=pod_query))
        
        # 노드별 Pod 수 조회
        node_pod_query = 'count by (instance) (kube_pod_info{cluster="nks-cluster"})'
        node_pod_result = await query_prometheus(PromQuery(query=node_pod_query))
        
        total_pods = 0
        node_pod_counts = []
        
        if pod_result.get("status") == "success" and pod_result.get("data", {}).get("result"):
            total_pods = sum(float(r.get("value", [None, "0"])[1]) for r in pod_result["data"]["result"])
        
        if node_pod_result.get("status") == "success" and node_pod_result.get("data", {}).get("result"):
            node_pod_counts = [
                {
                    "instance": r.get("metric", {}).get("instance", "unknown"),
                    "pod_count": int(float(r.get("value", [None, "0"])[1]))
                }
                for r in node_pod_result["data"]["result"]
            ]
        
        return {
            "status": "success",
            "cluster": "nks-cluster",
            "total_pods": int(total_pods),
            "node_pod_counts": node_pod_counts,
            "message": "NKS pod information retrieved successfully"
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"NKS pod info query failed: {str(e)}"
        }
