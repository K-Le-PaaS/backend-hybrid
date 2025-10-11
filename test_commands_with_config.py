#!/usr/bin/env python3
"""
백엔드 Commands 테스트 (Config 경로 지정)

목적: 실제 백엔드 서비스의 commands.py를 테스트하여
      다른 클러스터(NKS 등)에서 명령어가 작동하는지 확인
"""

import os
import sys
import asyncio


async def test_commands_with_nks():
    """
    NKS 클러스터를 사용하여 commands.py의 명령어 테스트
    """
    
    # [1단계] 환경변수로 NKS kubeconfig 설정
    nks_config = os.path.expanduser("~/.kube/nks-kubeconfig.yaml")
    
    if not os.path.exists(nks_config):
        print(f"❌ NKS kubeconfig 파일을 찾을 수 없습니다: {nks_config}")
        sys.exit(1)
    
    # 환경변수 설정 (백엔드 서버가 읽을 설정)
    os.environ["KLEPAAS_K8S_CONFIG_FILE"] = nks_config
    
    print("=" * 70)
    print("🧪 백엔드 Commands 테스트 (NKS 클러스터)")
    print("=" * 70)
    print(f"📄 Config: {nks_config}\n")
    
    # [2단계] 백엔드 모듈 import
    from app.services.commands import plan_command, execute_command, CommandRequest
    
    # [3단계] 테스트 명령어 실행
    test_cases = [
        {
            "name": "상태 조회 (status)",
            "request": CommandRequest(
                command="status",
                app_name="k-le-paas-test01-deploy"  # NKS에 있는 실제 Deployment
            )
        },
        {
            "name": "로그 조회 (logs)",
            "request": CommandRequest(
                command="logs",
                app_name="k-le-paas-test01-deploy",
                lines=10
            )
        },
        {
            "name": "엔드포인트 조회 (endpoint)",
            "request": CommandRequest(
                command="endpoint",
                app_name="k-le-paas-test01-svc"  # NKS에 있는 실제 Service
            )
        }
    ]
    
    for test in test_cases:
        print("-" * 70)
        print(f"📝 테스트: {test['name']}")
        print("-" * 70)
        
        try:
            # plan_command: 명령어 해석
            plan = plan_command(test['request'])
            print(f"   계획: {plan.tool}")
            print(f"   인자: {plan.args}")
            
            # execute_command: 실제 Kubernetes API 호출
            result = await execute_command(plan)
            print(f"   결과: {result.get('status', 'unknown')}")
            
            if result.get('status') == 'success':
                print("   ✅ 성공!")
                # 상세 결과 일부 출력
                if 'deployment' in result:
                    dep = result['deployment']
                    print(f"      - Deployment: {dep.get('name')}")
                    print(f"      - Replicas: {dep['replicas']}")
                elif 'logs' in result:
                    print(f"      - Pod: {result.get('pod_name')}")
                    print(f"      - 로그 라인 수: {result.get('lines')}")
                elif 'endpoints' in result:
                    print(f"      - Service: {result.get('service_name')}")
                    print(f"      - Endpoints: {result.get('endpoints')}")
            else:
                print(f"   ⚠️  상태: {result.get('message', 'Unknown')}")
            
        except Exception as e:
            print(f"   ❌ 오류: {e}")
        
        print()
    
    print("=" * 70)
    print("✅ 테스트 완료!")
    print("=" * 70)


async def test_commands_with_local():
    """
    로컬 클러스터를 사용하여 commands.py의 명령어 테스트
    """
    
    # 환경변수 제거 (기본 ~/.kube/config 사용)
    if "KLEPAAS_K8S_CONFIG_FILE" in os.environ:
        del os.environ["KLEPAAS_K8S_CONFIG_FILE"]
    
    print("=" * 70)
    print("🧪 백엔드 Commands 테스트 (로컬 클러스터)")
    print("=" * 70)
    print(f"📄 Config: ~/.kube/config (기본값)\n")
    
    from app.services.commands import plan_command, execute_command, CommandRequest
    
    # 로컬 클러스터의 리소스 이름 사용
    test_cases = [
        {
            "name": "상태 조회 (status)",
            "request": CommandRequest(
                command="status",
                app_name="nfs-subdir-external-provisioner"
            )
        }
    ]
    
    for test in test_cases:
        print("-" * 70)
        print(f"📝 테스트: {test['name']}")
        print("-" * 70)
        
        try:
            plan = plan_command(test['request'])
            print(f"   계획: {plan.tool}")
            
            result = await execute_command(plan)
            print(f"   결과: {result.get('status', 'unknown')}")
            
            if result.get('status') == 'success':
                print("   ✅ 성공!")
            else:
                print(f"   ⚠️  {result.get('message')}")
            
        except Exception as e:
            print(f"   ❌ 오류: {e}")
        
        print()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="백엔드 Commands 테스트")
    parser.add_argument(
        "--cluster",
        choices=["nks", "local"],
        default="local",
        help="테스트할 클러스터 선택 (기본값: local)"
    )
    
    args = parser.parse_args()
    
    print("\n💡 사용법:")
    print("   python test_commands_with_config.py --cluster local   # 로컬 클러스터")
    print("   python test_commands_with_config.py --cluster nks     # NKS 클러스터")
    print()
    
    if args.cluster == "nks":
        asyncio.run(test_commands_with_nks())
    else:
        asyncio.run(test_commands_with_local())

