"""
WebSocket API 엔드포인트

실시간 배포 모니터링을 위한 WebSocket 엔드포인트입니다.
"""

import uuid
from typing import Dict, Any

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from fastapi.websockets import WebSocketState

from ...websocket.deployment_monitor import (
    get_deployment_monitor_manager,
    DeploymentMonitorManager
)

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.websocket("/ws/kubernetes")
async def websocket_kubernetes_monitor(websocket: WebSocket):
    """
    Kubernetes 리소스 모니터링 WebSocket 엔드포인트
    
    클라이언트는 이 엔드포인트에 연결하여 실시간 Kubernetes 리소스 상태를 받을 수 있습니다.
    """
    connection_id = str(uuid.uuid4())
    
    try:
        # WebSocket 연결 수락
        await websocket.accept()
        
        logger.info("kubernetes_websocket_connected", connection_id=connection_id)
        
        # 연결 확인 메시지 전송
        await websocket.send_json({
            "type": "connection",
            "data": {
                "status": "connected",
                "connection_id": connection_id,
                "message": "Kubernetes WebSocket 연결이 성공적으로 설정되었습니다."
            }
        })
        
        # 메시지 루프
        while True:
            try:
                # 메시지 수신
                data = await websocket.receive_json()
                
                # 핑/퐁 처리
                if data.get("type") == "ping":
                    await websocket.send_json({
                        "type": "pong",
                        "data": {"timestamp": str(uuid.uuid4())}
                    })
                elif data.get("type") == "subscribe":
                    # 구독 처리
                    namespace = data.get("data", {}).get("namespace", "default")
                    await websocket.send_json({
                        "type": "subscribed",
                        "data": {"namespace": namespace, "message": f"구독됨: {namespace}"}
                    })
                elif data.get("type") == "unsubscribe":
                    # 구독 해제 처리
                    namespace = data.get("data", {}).get("namespace", "default")
                    await websocket.send_json({
                        "type": "unsubscribed",
                        "data": {"namespace": namespace, "message": f"구독 해제됨: {namespace}"}
                    })
                else:
                    # 다른 메시지 처리
                    await websocket.send_json({
                        "type": "response",
                        "data": {"message": "메시지를 받았습니다.", "received": data}
                    })
                
            except WebSocketDisconnect:
                logger.info("kubernetes_websocket_disconnected", connection_id=connection_id)
                break
            except Exception as e:
                logger.error(
                    "kubernetes_websocket_error",
                    error=str(e),
                    connection_id=connection_id
                )
                break
    
    except Exception as e:
        logger.error(
            "kubernetes_websocket_connection_failed",
            error=str(e),
            connection_id=connection_id
        )
    
    finally:
        logger.info("kubernetes_websocket_cleanup", connection_id=connection_id)


@router.websocket("/ws/deployments")
async def websocket_deployment_monitor(
    websocket: WebSocket,
    manager: DeploymentMonitorManager = Depends(get_deployment_monitor_manager)
):
    """
    배포 모니터링 WebSocket 엔드포인트
    
    클라이언트는 이 엔드포인트에 연결하여 실시간 배포 상태를 받을 수 있습니다.
    
    메시지 형식:
    - 구독: {"type": "subscribe", "data": {"app_name": "myapp", "environment": "staging"}}
    - 구독 해제: {"type": "unsubscribe", "data": {"app_name": "myapp"}}
    - 핑: {"type": "ping"}
    """
    connection_id = str(uuid.uuid4())
    
    try:
        logger.info(f"WebSocket connection attempt: {connection_id}")
        
        # 매니저 초기화 확인
        if not manager.is_initialized:
            logger.info("Initializing DeploymentMonitorManager")
            await manager.initialize()
        
        # WebSocket 연결 수락
        logger.info(f"Accepting WebSocket connection: {connection_id}")
        
        # URL에서 deployment_id 추출 (선택적)
        deployment_id = None
        if "/deployment/" in str(websocket.url):
            try:
                deployment_id = str(websocket.url).split("/deployment/")[1].split("?")[0]
            except:
                pass
        
        await manager.connect(websocket, connection_id, deployment_id=deployment_id)
        
        logger.info("websocket_connection_established", connection_id=connection_id)
        
        # 메시지 루프
        while True:
            try:
                # 메시지 수신
                logger.info(f"Waiting for message from connection: {connection_id}")
                data = await websocket.receive_json()
                logger.info(f"Received message from {connection_id}: {data}")
                
                # 메시지 처리
                await manager.handle_message(connection_id, data)
                logger.info(f"Message processed successfully for {connection_id}")
                
            except WebSocketDisconnect:
                logger.info("websocket_disconnected", connection_id=connection_id)
                break
            except Exception as e:
                logger.error(
                    "websocket_message_error",
                    error=str(e),
                    connection_id=connection_id,
                    error_type=type(e).__name__
                )
                
                # 오류 발생 시 연결을 즉시 종료하지 않고 계속 유지
                try:
                    error_response = {
                        "type": "error",
                        "data": {
                            "error": f"Message processing failed: {str(e)}"
                        }
                    }
                    await websocket.send_json(error_response)
                except Exception as send_error:
                    logger.error(f"Failed to send error response: {send_error}")
                    break
    
    except Exception as e:
        logger.error(
            "websocket_connection_failed",
            error=str(e),
            connection_id=connection_id,
            error_type=type(e).__name__
        )
        # 연결 해제
        try:
            await manager.disconnect(connection_id)
        except:
            pass
    
    finally:
        # 연결 정리
        await manager.disconnect(connection_id)


@router.websocket("/ws/nks-monitoring")
async def websocket_nks_monitoring(websocket: WebSocket):
    """
    NKS 모니터링 실시간 WebSocket 엔드포인트
    
    클라이언트는 이 엔드포인트에 연결하여 NKS 클러스터의 실시간 모니터링 데이터를 받을 수 있습니다.
    
    메시지 형식:
    - 구독: {"type": "subscribe", "data": {"metrics": ["cpu", "memory", "disk", "network"]}}
    - 핑: {"type": "ping"}
    """
    connection_id = str(uuid.uuid4())
    
    try:
        # WebSocket 연결 수락
        await websocket.accept()
        
        logger.info("nks_monitoring_websocket_connected", connection_id=connection_id)
        
        # 연결 확인 메시지 전송
        await websocket.send_json({
            "type": "connection",
            "data": {
                "status": "connected",
                "connection_id": connection_id,
                "message": "NKS 모니터링 WebSocket 연결이 성공적으로 설정되었습니다."
            }
        })
        
        # NKS 모니터링 데이터 전송 루프
        import asyncio
        from ..services.prometheus_client import query_prometheus, PromQuery
        
        while True:
            try:
                # 클라이언트로부터 메시지 수신 (비차단)
                try:
                    data = await asyncio.wait_for(websocket.receive_json(), timeout=0.1)
                    
                    # 핑/퐁 처리
                    if data.get("type") == "ping":
                        await websocket.send_json({
                            "type": "pong",
                            "data": {"timestamp": str(uuid.uuid4())}
                        })
                        continue
                        
                except asyncio.TimeoutError:
                    # 메시지가 없으면 계속 진행
                    pass
                
                # NKS 모니터링 데이터 수집 및 전송
                try:
                    # CPU 사용률
                    cpu_query = PromQuery(query='100 - (avg(rate(node_cpu_seconds_total{cluster="nks-cluster", mode="idle"}[2m])) * 100)')
                    cpu_result = await query_prometheus(cpu_query)
                    
                    # 메모리 사용률
                    memory_query = PromQuery(query='(1 - (node_memory_MemAvailable_bytes{cluster="nks-cluster"} / node_memory_MemTotal_bytes{cluster="nks-cluster"})) * 100')
                    memory_result = await query_prometheus(memory_query)
                    
                    # 디스크 사용률
                    disk_query = PromQuery(query='100 - ((node_filesystem_avail_bytes{cluster="nks-cluster", mountpoint="/"} / node_filesystem_size_bytes{cluster="nks-cluster", mountpoint="/"}) * 100)')
                    disk_result = await query_prometheus(disk_query)
                    
                    # 네트워크 트래픽
                    inbound_task = asyncio.create_task(query_prometheus(PromQuery(query='rate(node_network_receive_bytes_total{cluster="nks-cluster"}[5m])')))
                    outbound_task = asyncio.create_task(query_prometheus(PromQuery(query='rate(node_network_transmit_bytes_total{cluster="nks-cluster"}[5m])')))
                    inbound_result, outbound_result = await asyncio.gather(inbound_task, outbound_task, return_exceptions=True)
                    
                    # 데이터 파싱
                    cpu_usage = None
                    if cpu_result.get("status") == "success" and cpu_result.get("data", {}).get("result"):
                        cpu_usage = round(float(cpu_result["data"]["result"][0]["value"][1]), 2)
                    
                    memory_usage = None
                    if memory_result.get("status") == "success" and memory_result.get("data", {}).get("result"):
                        memory_usage = round(float(memory_result["data"]["result"][0]["value"][1]), 2)
                    
                    disk_usage = None
                    if disk_result.get("status") == "success" and disk_result.get("data", {}).get("result"):
                        disk_usage = round(float(disk_result["data"]["result"][0]["value"][1]), 2)
                    
                    inbound_traffic = None
                    outbound_traffic = None
                    if not isinstance(inbound_result, Exception) and inbound_result.get("data", {}).get("result"):
                        total_inbound = sum(float(r.get("value", [None, "0"])[1]) for r in inbound_result["data"]["result"])
                        inbound_traffic = round(total_inbound / 1024 / 1024, 2)
                    
                    if not isinstance(outbound_result, Exception) and outbound_result.get("data", {}).get("result"):
                        total_outbound = sum(float(r.get("value", [None, "0"])[1]) for r in outbound_result["data"]["result"])
                        outbound_traffic = round(total_outbound / 1024 / 1024, 2)
                    
                    # 실시간 데이터 전송
                    monitoring_data = {
                        "type": "monitoring_data",
                        "data": {
                            "timestamp": datetime.utcnow().isoformat(),
                            "cluster": "nks-cluster",
                            "metrics": {
                                "cpu_usage": cpu_usage,
                                "memory_usage": memory_usage,
                                "disk_usage": disk_usage,
                                "network_traffic": {
                                    "inbound_mbps": inbound_traffic,
                                    "outbound_mbps": outbound_traffic
                                }
                            }
                        }
                    }
                    
                    await websocket.send_json(monitoring_data)
                    
                except Exception as e:
                    logger.error(f"NKS monitoring data collection failed: {e}")
                    await websocket.send_json({
                        "type": "error",
                        "data": {"error": f"Monitoring data collection failed: {str(e)}"}
                    })
                
                # 5초마다 데이터 전송
                await asyncio.sleep(5)
                
            except WebSocketDisconnect:
                logger.info("nks_monitoring_websocket_disconnected", connection_id=connection_id)
                break
            except Exception as e:
                logger.error(f"NKS monitoring WebSocket error: {e}")
                break
    
    except Exception as e:
        logger.error(f"NKS monitoring WebSocket connection failed: {e}")
    finally:
        logger.info("nks_monitoring_websocket_cleanup", connection_id=connection_id)


@router.get("/ws/stats")
async def get_websocket_stats(
    manager: DeploymentMonitorManager = Depends(get_deployment_monitor_manager)
) -> Dict[str, Any]:
    """
    WebSocket 연결 통계 조회
    
    현재 활성 연결 수, 구독 정보 등을 반환합니다.
    """
    try:
        return manager.get_connection_stats()
    except Exception as e:
        logger.error("websocket_stats_failed", error=str(e))
        return {
            "error": str(e),
            "active_connections": 0,
            "total_subscriptions": 0,
            "app_subscriptions": {}
        }
