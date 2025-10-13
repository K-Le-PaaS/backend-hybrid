#!/usr/bin/env python3
"""
NKS 파드 조회 테스트

목적: k8s_client.py의 load_kube_config()와 get_core_v1_api()를 사용하여
실제 NKS 클러스터에서 파드 정보를 조회하는 테스트

배경: 환경변수 KLEPAAS_K8S_CONFIG_FILE이 필수로 설정되어야 함
"""

import sys
from datetime import datetime

def test_pod_query():
    """NKS 클러스터의 파드를 조회하는 테스트"""
    
    print("=" * 80)
    print("NKS 파드 조회 테스트")
    print("=" * 80)
    print()
    
    try:
        # 1. k8s_client 모듈 임포트
        print("📦 1. k8s_client 모듈 로드 중...")
        from app.services.k8s_client import get_core_v1_api, get_apps_v1_api
        from app.core.config import get_settings
        print("   ✅ 모듈 로드 성공")
        print()
        
        # 2. 설정 확인
        print("⚙️  2. 환경 설정 확인...")
        settings = get_settings()
        print(f"   - KLEPAAS_K8S_CONFIG_FILE: {settings.k8s_config_file}")
        print(f"   - KLEPAAS_K8S_STAGING_NAMESPACE: {settings.k8s_staging_namespace}")
        print()
        
        # 3. Kubernetes API 클라이언트 생성
        print("🔌 3. Kubernetes API 연결 중...")
        core_v1 = get_core_v1_api()
        apps_v1 = get_apps_v1_api()
        print("   ✅ API 연결 성공")
        print()
        
        # 4. 네임스페이스 목록 조회
        print("📂 4. 네임스페이스 목록 조회...")
        namespaces = core_v1.list_namespace()
        print(f"   총 {len(namespaces.items)}개의 네임스페이스 발견:")
        for ns in namespaces.items[:5]:  # 상위 5개만 표시
            print(f"   - {ns.metadata.name}")
        if len(namespaces.items) > 5:
            print(f"   ... 외 {len(namespaces.items) - 5}개")
        print()
        
        # 5. default 네임스페이스의 파드 조회
        namespace = settings.k8s_staging_namespace or "default"
        print(f"🔍 5. '{namespace}' 네임스페이스의 파드 조회...")
        pods = core_v1.list_namespaced_pod(namespace=namespace)
        
        if not pods.items:
            print(f"   ⚠️  '{namespace}' 네임스페이스에 파드가 없습니다.")
        else:
            print(f"   총 {len(pods.items)}개의 파드 발견:")
            print()
            
            for idx, pod in enumerate(pods.items, 1):
                print(f"   [{idx}] 파드 정보:")
                print(f"       이름: {pod.metadata.name}")
                print(f"       상태: {pod.status.phase}")
                
                # 컨테이너 상태
                if pod.status.container_statuses:
                    for container in pod.status.container_statuses:
                        ready = "✅" if container.ready else "❌"
                        print(f"       컨테이너: {container.name} {ready}")
                        print(f"       재시작: {container.restart_count}회")
                        print(f"       이미지: {container.image}")
                
                # 생성 시간
                if pod.metadata.creation_timestamp:
                    age = datetime.now(pod.metadata.creation_timestamp.tzinfo) - pod.metadata.creation_timestamp
                    print(f"       생성: {age.days}일 {age.seconds // 3600}시간 전")
                
                print()
        
        # 6. Deployment 조회 (있다면)
        print(f"📦 6. '{namespace}' 네임스페이스의 Deployment 조회...")
        deployments = apps_v1.list_namespaced_deployment(namespace=namespace)
        
        if not deployments.items:
            print(f"   ⚠️  '{namespace}' 네임스페이스에 Deployment가 없습니다.")
        else:
            print(f"   총 {len(deployments.items)}개의 Deployment 발견:")
            print()
            
            for idx, deploy in enumerate(deployments.items, 1):
                print(f"   [{idx}] Deployment 정보:")
                print(f"       이름: {deploy.metadata.name}")
                print(f"       레플리카: {deploy.status.ready_replicas or 0}/{deploy.spec.replicas}")
                print(f"       이미지: {deploy.spec.template.spec.containers[0].image}")
                print()
        
        # 7. 전체 클러스터 노드 조회
        print("🖥️  7. 클러스터 노드 조회...")
        nodes = core_v1.list_node()
        print(f"   총 {len(nodes.items)}개의 노드:")
        for node in nodes.items:
            # 노드 상태 확인
            ready_status = "Unknown"
            for condition in node.status.conditions:
                if condition.type == "Ready":
                    ready_status = "Ready" if condition.status == "True" else "NotReady"
            
            print(f"   - {node.metadata.name}: {ready_status}")
            print(f"     OS: {node.status.node_info.os_image}")
            print(f"     Kubelet: {node.status.node_info.kubelet_version}")
        
        print()
        print("=" * 80)
        print("✅ 모든 테스트 성공!")
        print("=" * 80)
        return True
        
    except RuntimeError as e:
        print()
        print("❌ 환경변수 오류:")
        print(f"   {e}")
        print()
        print("💡 해결 방법:")
        print("   .env 파일에 다음을 추가하세요:")
        print("   KLEPAAS_K8S_CONFIG_FILE=/path/to/nks-kubeconfig.yaml")
        return False
        
    except FileNotFoundError as e:
        print()
        print("❌ 파일 오류:")
        print(f"   {e}")
        print()
        print("💡 해결 방법:")
        print("   kubeconfig 파일 경로를 확인하세요.")
        return False
        
    except Exception as e:
        print()
        print(f"❌ 예상치 못한 오류: {type(e).__name__}")
        print(f"   {e}")
        import traceback
        print()
        print("상세 오류:")
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_pod_query()
    sys.exit(0 if success else 1)

