#!/usr/bin/env python3
"""
========================================
Kubernetes 연결 테스트 스크립트
========================================

[목적]
- 로컬 kubeconfig를 사용하여 Kubernetes 클러스터에 연결
- default namespace의 리소스(Pod, Deployment, Service) 조회
- 백엔드 서버에서 사용할 k8s_client.py가 정상 작동하는지 검증

[실행 방법]
- python test_k8s_connection.py

[사용하는 kubeconfig]
- 기본: ~/.kube/config (로컬 클러스터 설정)
- k8s_client.py의 load_kube_config()가 자동으로 로드

[내부 동작]
1. app.services.k8s_client에서 헬퍼 함수 import
2. get_core_v1_api() -> CoreV1Api 객체 생성 (Pod, Service 관리용)
3. get_apps_v1_api() -> AppsV1Api 객체 생성 (Deployment 관리용)
4. Kubernetes API를 호출하여 리소스 정보 조회
5. 결과를 사용자 친화적 형식으로 출력
"""

import sys
# app/services/k8s_client.py에서 Kubernetes API 클라이언트 헬퍼 함수 import
# - get_core_v1_api(): Pod, Service, ConfigMap 등 core 리소스 관리
# - get_apps_v1_api(): Deployment, ReplicaSet 등 apps 리소스 관리
from app.services.k8s_client import get_core_v1_api, get_apps_v1_api


def test_list_pods():
    """
    [함수 목적]
    default namespace에 있는 모든 Pod의 상태를 조회하고 출력
    
    [실행 흐름]
    1. get_core_v1_api() 호출 -> kubeconfig 로드 -> API 클라이언트 생성
    2. list_namespaced_pod() 호출 -> Kubernetes API Server에 HTTPS 요청
    3. 응답 받은 Pod 목록을 Python 객체로 변환
    4. 각 Pod의 상태 정보 추출 및 출력
    
    [Kubernetes API 호출]
    GET https://<api-server>/api/v1/namespaces/default/pods
    """
    print("=" * 60)
    print("🔍 Kubernetes Pod 목록 조회 테스트")
    print("=" * 60)
    
    try:
        # [1단계] Core V1 API 클라이언트 생성
        # - app/services/k8s_client.py의 get_core_v1_api() 호출
        # - 내부에서 load_kube_config()로 ~/.kube/config 로드
        # - kubernetes.client.CoreV1Api() 인스턴스 반환
        core_v1 = get_core_v1_api()
        
        # [2단계] 현재 연결된 클러스터 정보 확인
        # - kubernetes 라이브러리에서 client 모듈 import
        # - Configuration 객체로 API Server 주소, 인증 정보 확인
        from kubernetes import client
        config = client.Configuration.get_default_copy()
        
        # config.host: kubeconfig에서 읽은 API Server URL (예: https://192.168.2.100:6443)
        print(f"\n📡 연결된 API Server: {config.host}")
        
        # config.api_key: Bearer Token이 있으면 True (ServiceAccount 방식)
        # 없으면 Certificate 방식 (클라이언트 인증서)
        print(f"🔐 인증 방식: {'Bearer Token' if config.api_key else 'Certificate'}")
        
        # [3단계] default namespace의 Pod 목록 조회
        print(f"\n📦 Namespace: default")
        print("-" * 60)
        
        # list_namespaced_pod(): CoreV1Api의 메서드
        # 실제 HTTP 요청: GET /api/v1/namespaces/{namespace}/pods
        # 반환값: V1PodList 객체 (items 속성에 Pod 리스트 포함)
        pods = core_v1.list_namespaced_pod(namespace="default")
        
        # pods.items: V1Pod 객체들의 리스트
        # Pod가 없으면 빈 리스트 ([])
        if not pods.items:
            print("⚠️  Pod가 없습니다.")
            return
        
        # len(pods.items): Pod 개수 확인
        print(f"✅ 총 {len(pods.items)}개의 Pod 발견\n")
        
        # [4단계] 각 Pod의 상세 정보 출력
        # enumerate(): (인덱스, 값) 튜플 반환, 1부터 시작
        for i, pod in enumerate(pods.items, 1):
            # pod.metadata.name: Pod 이름 (예: "nginx-deployment-7d64c8f865-abcde")
            print(f"{i}. Pod: {pod.metadata.name}")
            
            # pod.status.phase: Pod 생명주기 상태
            # - Pending: 생성 중
            # - Running: 실행 중
            # - Succeeded: 성공적으로 종료
            # - Failed: 실패
            # - Unknown: 알 수 없음
            print(f"   상태: {pod.status.phase}")
            
            # pod.status.pod_ip: Pod에 할당된 클러스터 내부 IP 주소
            # None일 경우 'N/A' 표시
            print(f"   IP: {pod.status.pod_ip or 'N/A'}")
            
            # pod.spec.node_name: Pod가 실행되는 Node 이름
            # 스케줄링 전에는 None
            print(f"   Node: {pod.spec.node_name or 'N/A'}")
            
            # [5단계] Container 정보 출력
            # pod.spec.containers: Pod 내 Container 정의 리스트
            # 하나의 Pod는 여러 Container를 가질 수 있음 (sidecar 패턴 등)
            if pod.spec.containers:
                print(f"   Containers:")
                for container in pod.spec.containers:
                    # container.name: Container 이름
                    # container.image: Container 이미지 (예: "nginx:1.21")
                    print(f"     - {container.name} ({container.image})")
            
            # [6단계] Container 실행 상태 확인
            # pod.status.container_statuses: 실제 Container 실행 상태
            # spec.containers는 '정의', status.container_statuses는 '현재 상태'
            if pod.status.container_statuses:
                for status in pod.status.container_statuses:
                    # status.ready: Container가 Ready 상태인지 (트래픽 받을 준비됨)
                    ready = "✅" if status.ready else "❌"
                    
                    # status.name: Container 이름
                    # status.ready: 준비 상태 (True/False)
                    # status.restart_count: Container 재시작 횟수 (높으면 문제 있음)
                    print(f"     {ready} {status.name}: Ready={status.ready}, Restarts={status.restart_count}")
            
            print()
        
    # [예외 처리]
    # Kubernetes API 호출 중 발생할 수 있는 오류:
    # - ApiException: API Server 응답 오류 (404, 403 등)
    # - ConnectionError: 네트워크 연결 오류
    # - ConfigException: kubeconfig 파일 오류
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        # traceback.print_exc(): 상세한 오류 스택 출력 (디버깅용)
        import traceback
        traceback.print_exc()
        sys.exit(1)


def test_list_deployments():
    """
    [함수 목적]
    default namespace의 Deployment 목록과 상태 조회
    
    [Deployment란?]
    - Kubernetes에서 애플리케이션 배포를 관리하는 리소스
    - ReplicaSet을 통해 Pod 개수 관리 (스케일링, 롤링 업데이트)
    - 예: "nginx 서버 3개 실행"
    
    [Kubernetes API 호출]
    GET https://<api-server>/apis/apps/v1/namespaces/default/deployments
    """
    print("=" * 60)
    print("🚀 Kubernetes Deployment 목록 조회 테스트")
    print("=" * 60)
    
    try:
        # [1단계] Apps V1 API 클라이언트 생성
        # - CoreV1Api와 다른 API 그룹 (apps/v1)
        # - Deployment, StatefulSet, DaemonSet 관리
        apps_v1 = get_apps_v1_api()
        
        # [2단계] Deployment 목록 조회
        # list_namespaced_deployment(): AppsV1Api의 메서드
        # 실제 HTTP 요청: GET /apis/apps/v1/namespaces/{namespace}/deployments
        # 반환값: V1DeploymentList 객체
        deployments = apps_v1.list_namespaced_deployment(namespace="default")
        
        # deployments.items: V1Deployment 객체들의 리스트
        if not deployments.items:
            print("⚠️  Deployment가 없습니다.")
            return
        
        print(f"\n✅ 총 {len(deployments.items)}개의 Deployment 발견\n")
        
        # [3단계] 각 Deployment 정보 출력
        for i, deployment in enumerate(deployments.items, 1):
            # deployment.metadata.name: Deployment 이름
            print(f"{i}. Deployment: {deployment.metadata.name}")
            
            # deployment.status.replicas: 현재 실행 중인 Pod 총 개수
            # None일 수 있으므로 or 0 사용
            print(f"   Replicas: {deployment.status.replicas or 0}")
            
            # deployment.status.ready_replicas: Ready 상태인 Pod 개수
            # deployment.spec.replicas: 원하는 Pod 개수 (의도한 상태)
            # 예: "Ready: 3/3" -> 3개 모두 정상 실행 중
            print(f"   Ready: {deployment.status.ready_replicas or 0}/{deployment.spec.replicas}")
            
            # deployment.status.available_replicas: 사용 가능한 Pod 개수
            # Ready와 비슷하지만, 최소 준비 시간(minReadySeconds)을 만족한 Pod만 카운트
            print(f"   Available: {deployment.status.available_replicas or 0}")
            
            # [4단계] 사용 중인 Container 이미지 확인
            # deployment.spec.template.spec.containers: Pod template의 Container 정의
            # 첫 번째 Container의 이미지 출력 (보통 main container)
            if deployment.spec.template.spec.containers:
                container = deployment.spec.template.spec.containers[0]
                # container.image: Docker 이미지 (예: "nginx:1.21")
                print(f"   Image: {container.image}")
            
            print()
        
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()


def test_list_services():
    """
    [함수 목적]
    default namespace의 Service 목록과 엔드포인트 조회
    
    [Service란?]
    - Pod에 대한 네트워크 접근을 제공하는 추상화 계층
    - Pod IP는 변경될 수 있지만, Service는 고정된 ClusterIP 제공
    - 유형: ClusterIP (내부), NodePort, LoadBalancer (외부)
    
    [Kubernetes API 호출]
    GET https://<api-server>/api/v1/namespaces/default/services
    """
    print("=" * 60)
    print("🌐 Kubernetes Service 목록 조회 테스트")
    print("=" * 60)
    
    try:
        # [1단계] Core V1 API 클라이언트 생성
        # Service는 core/v1 API 그룹에 속함 (Pod와 동일)
        core_v1 = get_core_v1_api()
        
        # [2단계] Service 목록 조회
        # list_namespaced_service(): CoreV1Api의 메서드
        # 실제 HTTP 요청: GET /api/v1/namespaces/{namespace}/services
        # 반환값: V1ServiceList 객체
        services = core_v1.list_namespaced_service(namespace="default")
        
        if not services.items:
            print("⚠️  Service가 없습니다.")
            return
        
        print(f"\n✅ 총 {len(services.items)}개의 Service 발견\n")
        
        for i, service in enumerate(services.items, 1):
            print(f"{i}. Service: {service.metadata.name}")
            print(f"   Type: {service.spec.type}")
            print(f"   Cluster IP: {service.spec.cluster_ip}")
            
            if service.spec.ports:
                print(f"   Ports:")
                for port in service.spec.ports:
                    print(f"     - {port.port}:{port.target_port} ({port.protocol})")
            
            # LoadBalancer Ingress 정보
            if service.spec.type == "LoadBalancer" and service.status.load_balancer.ingress:
                for ingress in service.status.load_balancer.ingress:
                    ip_or_host = ingress.ip or ingress.hostname
                    print(f"   External: {ip_or_host}")
            
            print()
        
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()


def test_cluster_info():
    """클러스터 기본 정보 조회"""
    print("=" * 60)
    print("ℹ️  Kubernetes 클러스터 정보")
    print("=" * 60)
    
    try:
        core_v1 = get_core_v1_api()
        
        # Namespace 목록
        namespaces = core_v1.list_namespace()
        print(f"\n📁 사용 가능한 Namespace ({len(namespaces.items)}개):")
        for ns in namespaces.items:
            status = ns.status.phase
            print(f"   - {ns.metadata.name} ({status})")
        
        # Node 정보
        print(f"\n🖥️  Node 정보:")
        nodes = core_v1.list_node()
        for node in nodes.items:
            print(f"   - {node.metadata.name}")
            
            # Node 상태
            for condition in node.status.conditions:
                if condition.type == "Ready":
                    status = "✅ Ready" if condition.status == "True" else "❌ Not Ready"
                    print(f"     {status}")
            
            # Node 정보
            if node.status.node_info:
                info = node.status.node_info
                print(f"     OS: {info.os_image}")
                print(f"     Kernel: {info.kernel_version}")
                print(f"     Container Runtime: {info.container_runtime_version}")
        
        print()
        
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    print("\n🎯 Kubernetes 연결 테스트 시작\n")
    
    # 클러스터 정보
    test_cluster_info()
    
    print()
    
    # Pod 목록
    test_list_pods()
    
    print()
    
    # Deployment 목록
    test_list_deployments()
    
    print()
    
    # Service 목록
    test_list_services()
    
    print("\n✅ 모든 테스트 완료!")
    print("\n💡 팁: 특정 namespace를 테스트하려면 코드에서 'default'를 원하는 namespace로 변경하세요.")

