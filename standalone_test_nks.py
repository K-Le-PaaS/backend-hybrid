#!/usr/bin/env python3
"""
========================================
독립 실행형 NKS 연결 테스트
========================================

[특징]
- ✅ 프로젝트 종속성 없음 (app 모듈 import 불필요)
- ✅ 단일 파일로 완전히 독립적으로 실행 가능
- ✅ kubernetes 패키지만 필요 (pip install kubernetes)
- ✅ NKS (Naver Cloud Kubernetes Service) 전용

[실행 방법]
python standalone_test_nks.py

[필요한 패키지]
pip install kubernetes

[필요한 파일]
- ~/.kube/nks-kubeconfig.yaml (NKS 콘솔에서 다운로드)

[NKS kubeconfig 다운로드]
1. NCP 콘솔 > Server > Kubernetes Service
2. 클러스터 선택 > 설정 보기
3. kubeconfig 다운로드
4. ~/.kube/nks-kubeconfig.yaml로 저장
"""

import os
import sys


def main():
    """
    [메인 함수]
    NKS 클러스터에 연결하고 모든 리소스 조회
    
    [실행 흐름]
    1. nks-kubeconfig.yaml 파일 존재 확인
    2. kubernetes 라이브러리로 config 로드
    3. API 클라이언트 생성
    4. Namespace, Node, Pod, Deployment, Service 조회
    5. 결과 출력
    """
    
    # [1단계] NKS kubeconfig 파일 경로 확인
    nks_config = os.path.expanduser("~/.kube/nks-kubeconfig.yaml")
    
    if not os.path.exists(nks_config):
        print("❌ NKS kubeconfig 파일을 찾을 수 없습니다.")
        print(f"   경로: {nks_config}")
        print()
        print("💡 해결 방법:")
        print("   1. NCP 콘솔 > Server > Kubernetes Service")
        print("   2. 클러스터 선택 > 설정 보기")
        print("   3. kubeconfig 다운로드")
        print("   4. ~/.kube/nks-kubeconfig.yaml로 저장")
        print()
        print("   또는 다른 경로에 있다면:")
        print("   KUBECONFIG=/path/to/nks-config.yaml python standalone_test_nks.py")
        sys.exit(1)
    
    try:
        # [2단계] Kubernetes Python Client import
        from kubernetes import client, config
        
        print("\n🌐 NKS (Naver Cloud Kubernetes Service) 연결 테스트 (독립 실행형)\n")
        print("=" * 70)
        print(f"📄 Config 파일: {nks_config}")
        print()
        
        # [3단계] NKS kubeconfig 로드
        # config.load_kube_config(): 지정된 파일에서 설정 로드
        # - API Server URL
        # - 인증 정보 (client certificate, token 등)
        # - 클러스터 CA 인증서
        config.load_kube_config(config_file=nks_config)
        
        # [4단계] API Server 정보 확인
        configuration = client.Configuration.get_default_copy()
        print(f"📡 API Server: {configuration.host}")
        
        # NKS는 고유한 도메인 사용
        # 형식: https://<cluster-id>.kr.vnks.ntruss.com
        if "vnks.ntruss.com" in configuration.host:
            print("✅ NKS 클러스터로 확인됨")
        else:
            print("⚠️  NKS 클러스터가 아닐 수 있습니다")
        print()
        
        # [5단계] API 클라이언트 생성
        core_v1 = client.CoreV1Api()
        apps_v1 = client.AppsV1Api()
        
        # ==================== Namespace 목록 ====================
        print("=" * 70)
        print("📁 Namespace 목록")
        print("=" * 70)
        
        # list_namespace(): 모든 namespace 조회
        # HTTP 요청: GET /api/v1/namespaces
        namespaces = core_v1.list_namespace()
        
        print()
        for ns in namespaces.items:
            status = ns.status.phase
            print(f"   - {ns.metadata.name} ({status})")
        
        print(f"\n✅ 총 {len(namespaces.items)}개의 Namespace")
        
        # ==================== Node 정보 ====================
        print("\n")
        print("=" * 70)
        print("🖥️  Node 정보")
        print("=" * 70)
        
        # list_node(): 모든 Node 조회
        # HTTP 요청: GET /api/v1/nodes
        # NKS는 워커 노드를 자동으로 프로비저닝
        nodes = core_v1.list_node()
        
        print()
        for node in nodes.items:
            print(f"   📦 {node.metadata.name}")
            
            # Ready 상태
            for condition in node.status.conditions:
                if condition.type == "Ready":
                    status = "✅ Ready" if condition.status == "True" else "❌ Not Ready"
                    print(f"      {status}")
            
            # Node 정보
            if node.status.node_info:
                info = node.status.node_info
                print(f"      OS: {info.os_image}")
                print(f"      Container Runtime: {info.container_runtime_version}")
            
            # 리소스 용량
            if node.status.allocatable:
                print(f"      CPU: {node.status.allocatable.get('cpu', 'N/A')}")
                print(f"      Memory: {node.status.allocatable.get('memory', 'N/A')}")
            
            print()
        
        print(f"✅ 총 {len(nodes.items)}개의 Node")
        
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
                print(f"{i}. {pod.metadata.name}")
                print(f"   상태: {pod.status.phase}")
                print(f"   IP: {pod.status.pod_ip or 'N/A'}")
                print(f"   Node: {pod.spec.node_name or 'N/A'}")
                
                # Container 실행 상태
                if pod.status.container_statuses:
                    for status in pod.status.container_statuses:
                        ready = "✅" if status.ready else "❌"
                        print(f"   {ready} {status.name}: Ready={status.ready}, Restarts={status.restart_count}")
                
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
                print(f"{i}. {deployment.metadata.name}")
                print(f"   Replicas: {deployment.status.replicas or 0}")
                print(f"   Ready: {deployment.status.ready_replicas or 0}/{deployment.spec.replicas}")
                
                if deployment.spec.template.spec.containers:
                    container = deployment.spec.template.spec.containers[0]
                    print(f"   Image: {container.image}")
                    
                    # NCR (Naver Container Registry) 이미지 확인
                    if "ncr.ntruss.com" in container.image:
                        print(f"   🏷️  NCR 이미지 (Naver Container Registry)")
                
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
                print(f"{i}. {service.metadata.name}")
                print(f"   Type: {service.spec.type}")
                print(f"   Cluster IP: {service.spec.cluster_ip}")
                
                if service.spec.ports:
                    port_list = [f"{p.port}:{p.target_port}" for p in service.spec.ports]
                    print(f"   Ports: {', '.join(port_list)}")
                
                # LoadBalancer 외부 접속 정보
                # NKS LoadBalancer는 NCP Load Balancer와 연동
                if service.spec.type == "LoadBalancer":
                    if service.status.load_balancer.ingress:
                        for ingress in service.status.load_balancer.ingress:
                            ip_or_host = ingress.ip or ingress.hostname
                            print(f"   External: {ip_or_host}")
                            print(f"   🔗 NCP Load Balancer 연동됨")
                    else:
                        print(f"   External: Pending (LoadBalancer 생성 중)")
                
                print()
        
        print("=" * 70)
        print("✅ NKS 클러스터 연결 테스트 완료!")
        print("=" * 70)
        print()
        
        # 추가 정보
        print("💡 다음 단계:")
        print("   - Pod 로그 확인: kubectl logs <pod-name>")
        print("   - Deployment 스케일: kubectl scale deployment <name> --replicas=3")
        print("   - Service 접속: kubectl port-forward service/<name> 8080:80")
        print()
        
    except ImportError:
        print("❌ kubernetes 패키지가 설치되지 않았습니다.")
        print("   설치 방법: pip install kubernetes")
        sys.exit(1)
        
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        print("\n[가능한 원인]")
        print("- kubeconfig 파일이 잘못되었거나 손상됨")
        print("- NKS API Server에 접근할 수 없음 (네트워크 문제)")
        print("- 인증 정보가 만료됨 (NCP 콘솔에서 새로 다운로드)")
        print("- RBAC 권한 부족 (클러스터 관리자 권한 필요)")
        print()
        
        # 상세 오류 출력
        import traceback
        print("상세 오류:")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    """
    [실행 지점]
    python standalone_test_nks.py 명령으로 실행 시 이 블록이 실행됨
    
    [NKS 특징]
    - Naver Cloud Platform의 관리형 Kubernetes 서비스
    - 클러스터 생성/삭제/스케일링을 콘솔에서 수행
    - NCR (Naver Container Registry)와 자동 통합
    - NCP Load Balancer와 자동 연동
    
    [사용 예시]
    # 기본 실행
    python standalone_test_nks.py
    
    # 다른 kubeconfig 사용
    KUBECONFIG=/path/to/other-nks-config.yaml python standalone_test_nks.py
    
    # 디버그 모드 (상세 로그 출력)
    # Python 로깅 레벨 설정 추가 가능
    """
    main()

