#!/usr/bin/env python3
"""
========================================
NKS (Naver Cloud Kubernetes Service) 연결 테스트
========================================

[목적]
- NKS kubeconfig를 사용하여 Naver Cloud의 Kubernetes 클러스터에 연결
- NKS 클러스터의 리소스 조회 및 상태 확인
- 로컬 클러스터와 NKS 클러스터 접근 방식 비교

[NKS란?]
- Naver Cloud Platform에서 제공하는 관리형 Kubernetes 서비스
- 클러스터 생성, 관리, 모니터링을 웹 콘솔에서 수행
- kubeconfig 파일을 다운로드하여 kubectl 또는 SDK로 접근

[실행 방법]
1. 직접 실행: python test_nks_connection.py
2. kubeconfig 지정: KUBECONFIG=~/.kube/nks-kubeconfig.yaml python test_nks_connection.py

[사용하는 kubeconfig]
- ~/.kube/nks-kubeconfig.yaml (NKS 콘솔에서 다운로드)
- API Server: https://<cluster-id>.kr.vnks.ntruss.com

[로컬 클러스터와의 차이점]
- 로컬: 온프레미스 서버, 직접 설치 및 관리
- NKS: 클라우드 관리형, 자동 업데이트 및 스케일링
"""

import os
import sys


def test_nks_connection():
    """
    [함수 목적]
    NKS 클러스터에 연결하고 모든 리소스 조회
    
    [실행 흐름]
    1. nks-kubeconfig.yaml 파일 존재 확인
    2. KUBECONFIG 환경변수 설정
    3. Kubernetes Python Client로 config 로드
    4. Namespace, Node, Pod, Deployment, Service 조회
    
    [환경변수 설정 이유]
    - KUBECONFIG: kubernetes 라이브러리가 참조하는 표준 환경변수
    - 설정하면 config.load_kube_config()가 자동으로 해당 파일 사용
    """
    
    # [1단계] NKS kubeconfig 파일 경로 확인
    # os.path.expanduser("~"): 현재 사용자 홈 디렉토리로 확장 (예: /Users/yoon)
    nks_config = os.path.expanduser("~/.kube/nks-kubeconfig.yaml")
    
    # os.path.exists(): 파일 존재 여부 확인
    # NKS 콘솔에서 kubeconfig를 다운로드하지 않았으면 에러
    if not os.path.exists(nks_config):
        print(f"❌ NKS kubeconfig 파일을 찾을 수 없습니다: {nks_config}")
        print("💡 NKS 콘솔에서 kubeconfig를 다운로드하여 ~/.kube/ 디렉토리에 저장하세요.")
        sys.exit(1)
    
    print("=" * 70)
    print("🌐 NKS (Naver Cloud Kubernetes Service) 연결 테스트")
    print("=" * 70)
    print(f"📄 Config 파일: {nks_config}\n")
    
    # [2단계] 환경변수 설정
    # os.environ: Python 프로세스의 환경변수 딕셔너리
    # KUBECONFIG를 설정하면 kubernetes 라이브러리가 해당 파일을 우선 사용
    os.environ["KUBECONFIG"] = nks_config
    
    try:
        # [3단계] Kubernetes Python Client import
        # kubernetes 패키지 설치 필요: pip install kubernetes
        from kubernetes import client, config
        
        # config.load_kube_config(): kubeconfig 파일 로드
        # - 인자 없으면 KUBECONFIG 환경변수 또는 ~/.kube/config 사용
        # - config_file 인자로 명시적 지정 가능
        # - 내부에서 API Server 주소, 인증 정보 파싱
        config.load_kube_config(config_file=nks_config)
        
        # [4단계] API Server 정보 출력
        # client.Configuration: Kubernetes 클라이언트 설정 관리
        # get_default_copy(): 현재 로드된 설정의 복사본 반환
        configuration = client.Configuration.get_default_copy()
        
        # configuration.host: API Server URL
        # NKS는 고유한 도메인 사용 (예: https://69b2edb8-xxx.kr.vnks.ntruss.com)
        print(f"📡 API Server: {configuration.host}")
        print()
        
        # [5단계] API 클라이언트 생성
        # CoreV1Api: Pod, Service, Namespace 등 core 리소스 관리
        core_v1 = client.CoreV1Api()
        
        # AppsV1Api: Deployment, StatefulSet 등 apps 리소스 관리
        apps_v1 = client.AppsV1Api()
        
        # ==================== Namespace 조회 ====================
        print("📁 Namespace 목록:")
        print("-" * 70)
        
        # list_namespace(): 모든 namespace 조회 (클러스터 전체)
        # 실제 HTTP 요청: GET /api/v1/namespaces
        # 권한이 있어야 실행 가능 (cluster-admin 또는 적절한 RBAC)
        namespaces = core_v1.list_namespace()
        
        # 각 namespace 이름과 상태 출력
        for ns in namespaces.items:
            # ns.status.phase: namespace 상태
            # - Active: 정상 사용 중
            # - Terminating: 삭제 진행 중
            status = ns.status.phase
            print(f"   - {ns.metadata.name} ({status})")
        print()
        
        # ==================== Node 정보 조회 ====================
        print("🖥️  Node 정보:")
        print("-" * 70)
        
        # list_node(): 모든 Node 조회
        # 실제 HTTP 요청: GET /api/v1/nodes
        # Node: Kubernetes 클러스터의 워커 머신 (VM 또는 물리 서버)
        nodes = core_v1.list_node()
        
        for node in nodes.items:
            # node.metadata.name: Node 이름 (NKS는 자동 생성 이름 사용)
            print(f"   📦 {node.metadata.name}")
            
            # Node 상태 확인
            # node.status.conditions: Node의 다양한 상태 조건들
            # - Ready: Pod를 실행할 수 있는 상태
            # - MemoryPressure: 메모리 부족
            # - DiskPressure: 디스크 부족
            # - PIDPressure: 프로세스 ID 부족
            for condition in node.status.conditions:
                if condition.type == "Ready":
                    # condition.status: "True" 또는 "False" (문자열)
                    status = "✅ Ready" if condition.status == "True" else "❌ Not Ready"
                    print(f"      {status}")
            
            # Node 시스템 정보
            # node.status.node_info: OS, 커널, Container Runtime 정보
            if node.status.node_info:
                info = node.status.node_info
                # info.os_image: OS 버전 (예: "Ubuntu 22.04.3 LTS")
                print(f"      OS: {info.os_image}")
                
                # info.container_runtime_version: Container Runtime (예: "containerd://1.7.27")
                print(f"      Container Runtime: {info.container_runtime_version}")
            
            # Node 리소스 용량
            # node.status.allocatable: Pod에 할당 가능한 리소스
            # (capacity - 시스템 예약 = allocatable)
            if node.status.allocatable:
                # CPU 단위: 1000m = 1 core
                print(f"      CPU: {node.status.allocatable.get('cpu', 'N/A')}")
                
                # Memory 단위: Ki (Kibibyte), Mi, Gi
                print(f"      Memory: {node.status.allocatable.get('memory', 'N/A')}")
            
            print()
        
        # ==================== Pod 목록 조회 ====================
        print("📦 default Namespace - Pod 목록:")
        print("-" * 70)
        
        # list_namespaced_pod(): 특정 namespace의 Pod 목록 조회
        # 실제 HTTP 요청: GET /api/v1/namespaces/default/pods
        pods = core_v1.list_namespaced_pod(namespace="default")
        
        if not pods.items:
            print("   ⚠️  Pod가 없습니다.")
        else:
            print(f"   ✅ 총 {len(pods.items)}개의 Pod 발견\n")
            
            for i, pod in enumerate(pods.items, 1):
                # pod.metadata.name: Pod 이름 (Deployment가 생성하면 자동 접미사 추가)
                print(f"   {i}. {pod.metadata.name}")
                
                # pod.status.phase: Pod 생명주기 단계
                # - Pending: 스케줄링 대기 또는 이미지 다운로드 중
                # - Running: 실행 중
                # - Succeeded: 정상 종료 (Job/CronJob 등)
                # - Failed: 실패
                # - Unknown: Node와 통신 불가
                print(f"      상태: {pod.status.phase}")
                
                # pod.status.pod_ip: Pod에 할당된 IP (클러스터 내부에서만 접근 가능)
                print(f"      IP: {pod.status.pod_ip or 'N/A'}")
                
                # pod.spec.node_name: Pod가 실행 중인 Node 이름
                print(f"      Node: {pod.spec.node_name or 'N/A'}")
                
                # Container 상태 확인
                # pod.status.container_statuses: 각 Container의 실행 상태
                if pod.status.container_statuses:
                    for status in pod.status.container_statuses:
                        # status.ready: Readiness Probe 통과 여부
                        # Ready = True: 트래픽 수신 가능
                        # Ready = False: 아직 준비 안 됨 또는 문제 발생
                        ready = "✅" if status.ready else "❌"
                        
                        # status.restart_count: Container 재시작 횟수
                        # 높으면 CrashLoopBackOff 등 문제 가능성
                        print(f"      {ready} {status.name}: Ready={status.ready}, Restarts={status.restart_count}")
                print()
        
        # ==================== Deployment 목록 조회 ====================
        print("🚀 default Namespace - Deployment 목록:")
        print("-" * 70)
        
        # list_namespaced_deployment(): 특정 namespace의 Deployment 목록 조회
        # 실제 HTTP 요청: GET /apis/apps/v1/namespaces/default/deployments
        deployments = apps_v1.list_namespaced_deployment(namespace="default")
        
        if not deployments.items:
            print("   ⚠️  Deployment가 없습니다.")
        else:
            print(f"   ✅ 총 {len(deployments.items)}개의 Deployment 발견\n")
            
            for i, deployment in enumerate(deployments.items, 1):
                print(f"   {i}. {deployment.metadata.name}")
                
                # deployment.status.replicas: 현재 존재하는 총 Pod 수
                print(f"      Replicas: {deployment.status.replicas or 0}")
                
                # deployment.status.ready_replicas: Ready 상태인 Pod 수
                # deployment.spec.replicas: 의도한 Pod 수
                # 예: Ready: 3/3 = 모두 정상
                #     Ready: 1/3 = 2개 Pod 문제 발생
                print(f"      Ready: {deployment.status.ready_replicas or 0}/{deployment.spec.replicas}")
                
                # 사용 중인 Container 이미지
                if deployment.spec.template.spec.containers:
                    container = deployment.spec.template.spec.containers[0]
                    # NKS에서는 NCR(Naver Container Registry) 이미지 많이 사용
                    # 예: contest27-klepaas-build-handle.kr.ncr.ntruss.com/k-le-paas-test01@sha256:...
                    print(f"      Image: {container.image}")
                print()
        
        # ==================== Service 목록 조회 ====================
        print("🌐 default Namespace - Service 목록:")
        print("-" * 70)
        
        # list_namespaced_service(): 특정 namespace의 Service 목록 조회
        # 실제 HTTP 요청: GET /api/v1/namespaces/default/services
        services = core_v1.list_namespaced_service(namespace="default")
        
        if not services.items:
            print("   ⚠️  Service가 없습니다.")
        else:
            print(f"   ✅ 총 {len(services.items)}개의 Service 발견\n")
            
            for i, service in enumerate(services.items, 1):
                print(f"   {i}. {service.metadata.name}")
                
                # service.spec.type: Service 타입
                # - ClusterIP: 클러스터 내부에서만 접근 (기본값)
                # - NodePort: 모든 Node의 특정 포트로 접근
                # - LoadBalancer: 클라우드 LoadBalancer 생성 (NCP LB)
                # - ExternalName: 외부 DNS 이름으로 리다이렉트
                print(f"      Type: {service.spec.type}")
                
                # service.spec.cluster_ip: 클러스터 내부 고정 IP
                # Pod는 이 IP로 Service에 접근
                print(f"      Cluster IP: {service.spec.cluster_ip}")
                
                # service.spec.ports: Service가 노출하는 포트 목록
                if service.spec.ports:
                    # port: Service 포트 (클라이언트가 접근하는 포트)
                    # target_port: Pod 내 Container 포트 (실제 앱이 listen하는 포트)
                    # 예: "Ports: 80:8080" -> Service 80번 -> Container 8080번
                    port_list = [f"{p.port}:{p.target_port}" for p in service.spec.ports]
                    print(f"      Ports: {', '.join(port_list)}")
                
                # LoadBalancer의 외부 접속 정보
                # service.status.load_balancer.ingress: LoadBalancer의 IP 또는 도메인
                if service.spec.type == "LoadBalancer" and service.status.load_balancer.ingress:
                    for ingress in service.status.load_balancer.ingress:
                        # ingress.ip: LoadBalancer IP (NCP에서 자동 할당)
                        # ingress.hostname: LoadBalancer 도메인 (AWS ELB 등)
                        ip_or_host = ingress.ip or ingress.hostname
                        print(f"      External: {ip_or_host}")
                print()
        
        print("=" * 70)
        print("✅ NKS 클러스터 연결 테스트 완료!")
        print("=" * 70)
        
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        print("\n[가능한 원인]")
        print("- kubeconfig 파일 경로가 잘못됨")
        print("- API Server에 접근할 수 없음 (네트워크 문제)")
        print("- 인증 정보가 만료됨 (token 갱신 필요)")
        print("- RBAC 권한 부족 (클러스터 관리자에게 문의)")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def test_with_env_variable():
    """
    [함수 목적]
    백엔드 서버에서 사용할 환경변수 방식 테스트
    
    [배경]
    - 프로덕션 환경에서는 kubeconfig 파일 경로가 다를 수 있음
    - 환경변수 KLEPAAS_K8S_CONFIG_FILE로 경로 지정
    - app/core/config.py의 Settings에서 읽어 사용
    
    [실행 흐름]
    1. KLEPAAS_K8S_CONFIG_FILE 환경변수 설정
    2. app.services.k8s_client.get_core_v1_api() 호출
    3. 내부에서 Settings의 k8s_config_file 읽어 로드
    4. 간단한 API 호출로 연결 확인
    
    [백엔드 통합]
    이 방식으로 백엔드의 commands.py에서 NKS 클러스터 제어 가능
    """
    print("\n\n")
    print("=" * 70)
    print("🔧 환경변수 방식 테스트 (KLEPAAS_K8S_CONFIG_FILE)")
    print("=" * 70)
    
    nks_config = os.path.expanduser("~/.kube/nks-kubeconfig.yaml")
    
    # Settings를 통한 방식 시뮬레이션
    # KLEPAAS_ 접두사: app/core/config.py의 env_prefix 설정
    # 환경변수 이름: KLEPAAS_K8S_CONFIG_FILE
    # Settings 필드: k8s_config_file
    os.environ["KLEPAAS_K8S_CONFIG_FILE"] = nks_config
    
    print(f"KLEPAAS_K8S_CONFIG_FILE={nks_config}")
    print()
    
    try:
        # 기존 config 리셋 (다중 클러스터 전환 시 필요)
        from kubernetes import client, config
        from app.services.k8s_client import get_core_v1_api
        
        # get_core_v1_api() 호출
        # -> app/services/k8s_client.py의 load_kube_config() 실행
        # -> app/core/config.py의 get_settings() 호출
        # -> settings.k8s_config_file 읽음
        # -> 해당 파일로 config.load_kube_config() 실행
        core_v1 = get_core_v1_api()
        
        # 간단한 조회 테스트 (권한 문제 없는 namespace 조회)
        # 실제 HTTP 요청: GET /api/v1/namespaces
        namespaces = core_v1.list_namespace()
        
        print(f"✅ 환경변수를 통한 NKS 연결 성공!")
        print(f"   발견된 Namespace: {len(namespaces.items)}개")
        
        # 연결된 API Server 확인
        configuration = client.Configuration.get_default_copy()
        print(f"   API Server: {configuration.host}")
        
    except Exception as e:
        print(f"❌ 환경변수 방식 오류: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    """
    [메인 실행 흐름]
    1. test_nks_connection(): 직접 kubeconfig 파일 지정 방식
    2. test_with_env_variable(): 환경변수를 통한 방식 (백엔드 통합)
    
    [실행 결과 활용]
    - 두 방식 모두 성공하면 백엔드에서 NKS 클러스터 제어 가능
    - 실패 시 kubeconfig 파일, 네트워크, 권한 문제 확인 필요
    """
    
    # [테스트 1] 직접 파일 지정 방식
    # 장점: 명확하고 간단
    # 단점: 파일 경로 하드코딩
    test_nks_connection()
    
    # [테스트 2] 환경변수 방식 (권장)
    # 장점: 환경별로 다른 클러스터 사용 가능
    # 예: 로컬 개발 = ~/.kube/config
    #     스테이징 = ~/.kube/staging-kubeconfig.yaml
    #     프로덕션 = ~/.kube/nks-kubeconfig.yaml
    test_with_env_variable()
    
    print("\n💡 백엔드에서 NKS를 사용하려면:")
    print("   export KLEPAAS_K8S_CONFIG_FILE=~/.kube/nks-kubeconfig.yaml")
    print("   또는 .env 파일에 추가하세요:")
    print("   KLEPAAS_K8S_CONFIG_FILE=/Users/yoon/.kube/nks-kubeconfig.yaml")
