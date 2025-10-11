#!/usr/bin/env python3
"""
========================================
독립 실행형 Kubernetes 연결 테스트
========================================

[특징]
- ✅ 프로젝트 종속성 없음 (app 모듈 import 불필요)
- ✅ 단일 파일로 완전히 독립적으로 실행 가능
- ✅ kubernetes 패키지만 필요 (pip install kubernetes)

[실행 방법]
python standalone_test_k8s.py

[필요한 패키지]
pip install kubernetes

[사용하는 kubeconfig]
- 기본: ~/.kube/config
- 환경변수 KUBECONFIG 설정 시 해당 파일 사용
- 예: KUBECONFIG=/path/to/config.yaml python standalone_test_k8s.py
"""

import sys


def main():
    """
    [메인 함수]
    Kubernetes 클러스터에 연결하고 모든 리소스 조회
    
    [실행 흐름]
    1. kubernetes 라이브러리 import
    2. kubeconfig 로드 (in-cluster 또는 로컬 파일)
    3. API 클라이언트 생성 (CoreV1Api, AppsV1Api)
    4. 클러스터 정보, Namespace, Node, Pod, Deployment, Service 조회
    5. 결과를 사용자 친화적 형식으로 출력
    """
    
    try:
        # [1단계] Kubernetes Python Client import
        # 패키지 설치: pip install kubernetes
        from kubernetes import client, config
        
        print("\n🎯 Kubernetes 클러스터 연결 테스트 (독립 실행형)\n")
        print("=" * 70)
        
        # [2단계] Kubeconfig 로드
        # config.load_kube_config(): kubeconfig 파일 로드
        # 우선순위:
        # 1. In-cluster config (Pod 내부 실행 시)
        # 2. KUBECONFIG 환경변수
        # 3. ~/.kube/config (기본값)
        try:
            # Pod 내부에서 실행 중이면 ServiceAccount 토큰 사용
            config.load_incluster_config()
            print("📍 Config: In-Cluster (Pod 내부)")
        except:
            # 로컬 실행 시 kubeconfig 파일 로드
            config.load_kube_config()
            print("📍 Config: Local kubeconfig")
        
        # [3단계] API Server 정보 확인
        # Configuration 객체로 연결된 클러스터 정보 조회
        configuration = client.Configuration.get_default_copy()
        print(f"📡 API Server: {configuration.host}")
        print(f"🔐 인증 방식: {'Bearer Token' if configuration.api_key else 'Certificate'}")
        print()
        
        # [4단계] API 클라이언트 생성
        # CoreV1Api: Pod, Service, Namespace, ConfigMap, Secret 등
        # AppsV1Api: Deployment, StatefulSet, DaemonSet, ReplicaSet 등
        core_v1 = client.CoreV1Api()
        apps_v1 = client.AppsV1Api()
        
        # ==================== 클러스터 정보 ====================
        print("=" * 70)
        print("ℹ️  클러스터 정보")
        print("=" * 70)
        
        # [5단계] Namespace 목록 조회
        # list_namespace(): 모든 namespace 조회
        # HTTP 요청: GET /api/v1/namespaces
        print("\n📁 Namespace 목록:")
        namespaces = core_v1.list_namespace()
        for ns in namespaces.items:
            # ns.status.phase: Active(사용중) 또는 Terminating(삭제중)
            status = ns.status.phase
            print(f"   - {ns.metadata.name} ({status})")
        
        # [6단계] Node 정보 조회
        # list_node(): 모든 Node 조회
        # HTTP 요청: GET /api/v1/nodes
        print(f"\n🖥️  Node 목록:")
        nodes = core_v1.list_node()
        for node in nodes.items:
            print(f"   - {node.metadata.name}")
            
            # Node Ready 상태 확인
            for condition in node.status.conditions:
                if condition.type == "Ready":
                    status = "✅ Ready" if condition.status == "True" else "❌ Not Ready"
                    print(f"     {status}")
            
            # OS 및 Container Runtime 정보
            if node.status.node_info:
                info = node.status.node_info
                print(f"     OS: {info.os_image}")
                print(f"     Kernel: {info.kernel_version}")
                print(f"     Container Runtime: {info.container_runtime_version}")
        
        # ==================== Pod 목록 ====================
        print("\n")
        print("=" * 70)
        print("📦 Pod 목록 (default namespace)")
        print("=" * 70)
        
        # list_namespaced_pod(): 특정 namespace의 Pod 조회
        # HTTP 요청: GET /api/v1/namespaces/default/pods
        pods = core_v1.list_namespaced_pod(namespace="default")
        
        if not pods.items:
            print("\n⚠️  Pod가 없습니다.")
        else:
            print(f"\n✅ 총 {len(pods.items)}개의 Pod 발견\n")
            
            for i, pod in enumerate(pods.items, 1):
                print(f"{i}. Pod: {pod.metadata.name}")
                print(f"   상태: {pod.status.phase}")
                print(f"   IP: {pod.status.pod_ip or 'N/A'}")
                print(f"   Node: {pod.spec.node_name or 'N/A'}")
                
                # Container 정보
                if pod.spec.containers:
                    print(f"   Containers:")
                    for container in pod.spec.containers:
                        print(f"     - {container.name} ({container.image})")
                
                # Container 실행 상태
                if pod.status.container_statuses:
                    for status in pod.status.container_statuses:
                        ready = "✅" if status.ready else "❌"
                        print(f"     {ready} {status.name}: Ready={status.ready}, Restarts={status.restart_count}")
                
                print()
        
        # ==================== Deployment 목록 ====================
        print("=" * 70)
        print("🚀 Deployment 목록 (default namespace)")
        print("=" * 70)
        
        # list_namespaced_deployment(): 특정 namespace의 Deployment 조회
        # HTTP 요청: GET /apis/apps/v1/namespaces/default/deployments
        deployments = apps_v1.list_namespaced_deployment(namespace="default")
        
        if not deployments.items:
            print("\n⚠️  Deployment가 없습니다.")
        else:
            print(f"\n✅ 총 {len(deployments.items)}개의 Deployment 발견\n")
            
            for i, deployment in enumerate(deployments.items, 1):
                print(f"{i}. Deployment: {deployment.metadata.name}")
                print(f"   Replicas: {deployment.status.replicas or 0}")
                print(f"   Ready: {deployment.status.ready_replicas or 0}/{deployment.spec.replicas}")
                print(f"   Available: {deployment.status.available_replicas or 0}")
                
                if deployment.spec.template.spec.containers:
                    container = deployment.spec.template.spec.containers[0]
                    print(f"   Image: {container.image}")
                
                print()
        
        # ==================== Service 목록 ====================
        print("=" * 70)
        print("🌐 Service 목록 (default namespace)")
        print("=" * 70)
        
        # list_namespaced_service(): 특정 namespace의 Service 조회
        # HTTP 요청: GET /api/v1/namespaces/default/services
        services = core_v1.list_namespaced_service(namespace="default")
        
        if not services.items:
            print("\n⚠️  Service가 없습니다.")
        else:
            print(f"\n✅ 총 {len(services.items)}개의 Service 발견\n")
            
            for i, service in enumerate(services.items, 1):
                print(f"{i}. Service: {service.metadata.name}")
                print(f"   Type: {service.spec.type}")
                print(f"   Cluster IP: {service.spec.cluster_ip}")
                
                if service.spec.ports:
                    print(f"   Ports:")
                    for port in service.spec.ports:
                        print(f"     - {port.port}:{port.target_port} ({port.protocol})")
                
                # LoadBalancer 외부 접속 정보
                if service.spec.type == "LoadBalancer" and service.status.load_balancer.ingress:
                    for ingress in service.status.load_balancer.ingress:
                        ip_or_host = ingress.ip or ingress.hostname
                        print(f"   External: {ip_or_host}")
                
                print()
        
        print("=" * 70)
        print("✅ 테스트 완료!")
        print("=" * 70)
        print()
        
    except ImportError:
        print("❌ kubernetes 패키지가 설치되지 않았습니다.")
        print("   설치 방법: pip install kubernetes")
        sys.exit(1)
        
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        print("\n[가능한 원인]")
        print("- kubeconfig 파일이 없음 (~/.kube/config)")
        print("- Kubernetes 클러스터가 실행 중이 아님")
        print("- API Server에 접근할 수 없음 (네트워크 문제)")
        print("- 인증 정보가 만료되었거나 잘못됨")
        print()
        
        # 상세 오류 출력 (디버깅용)
        import traceback
        print("상세 오류:")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    """
    [실행 지점]
    python standalone_test_k8s.py 명령으로 실행 시 이 블록이 실행됨
    
    [특징]
    - import 문 최소화 (kubernetes만 사용)
    - 모든 로직을 main() 함수에 포함
    - 프로젝트의 다른 파일 참조 없음
    
    [사용 예시]
    # 기본 실행
    python standalone_test_k8s.py
    
    # 다른 kubeconfig 사용
    KUBECONFIG=/path/to/other-config.yaml python standalone_test_k8s.py
    
    # 특정 context 사용 (코드 수정 필요)
    # config.load_kube_config(context="my-context")
    """
    main()

