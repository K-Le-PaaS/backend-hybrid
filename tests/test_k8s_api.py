import asyncio
import httpx
import json

# 서버 URL
BASE_URL = "http://localhost:8000"

async def test_endpoint(client: httpx.AsyncClient, path: str, expected_status: int, method: str = "GET", json_data: dict = None, print_response: bool = True):
    """단일 엔드포인트를 테스트하고 결과를 반환합니다."""
    try:
        if method == "GET":
            response = await client.get(f"{BASE_URL}{path}")
        elif method == "POST":
            response = await client.post(f"{BASE_URL}{path}", json=json_data)
        elif method == "PUT":
            response = await client.put(f"{BASE_URL}{path}", json=json_data)
        elif method == "DELETE":
            response = await client.delete(f"{BASE_URL}{path}")
        else:
            raise ValueError(f"Unsupported method: {method}")

        status_ok = response.status_code == expected_status
        print(f"   {'✅' if status_ok else '❌'} {path}: {response.status_code}")
        if print_response:
            try:
                print(f"   📊 {response.json()}")
            except json.JSONDecodeError:
                print(f"   📊 {response.text[:100]}...")
        return status_ok, response
    except httpx.ConnectError as e:
        print(f"   ❌ {path}: 연결 실패 - {e}")
        return False, None
    except Exception as e:
        print(f"   ❌ {path}: 예상치 못한 오류 - {e}")
        return False, None

async def main():
    print("🚀 Kubernetes API 테스트 시작")
    print("==================================================\n")

    async with httpx.AsyncClient() as client:
        # 1. Kubernetes API 헬스체크
        print("1. Kubernetes API 헬스체크")
        status_ok, response = await test_endpoint(client, "/api/v1/health", 200, print_response=False)
        if status_ok and response:
            health_data = response.json()
            print(f"   📊 상태: {health_data.get('status')}")
            print(f"   📋 메시지: {health_data.get('message')}")

        # 2. Kubernetes 컨텍스트 목록
        print("\n2. Kubernetes 컨텍스트 목록")
        status_ok, response = await test_endpoint(client, "/api/v1/contexts", 200, print_response=False)
        if status_ok and response:
            contexts = response.json()
            print(f"   📊 컨텍스트 수: {len(contexts)}")
            for ctx in contexts:
                print(f"   🔧 {ctx.get('name')} {'(현재)' if ctx.get('current') else ''}")

        # 3. 네임스페이스 목록
        print("\n3. 네임스페이스 목록")
        status_ok, response = await test_endpoint(client, "/api/v1/namespaces", 200, print_response=False)
        if status_ok and response:
            namespaces = response.json()
            print(f"   📊 네임스페이스 수: {len(namespaces)}")
            for ns in namespaces[:3]:  # 처음 3개만 표시
                print(f"   📁 {ns.get('metadata', {}).get('name', 'Unknown')}")

        # 4. Deployment 목록 조회
        print("\n4. Deployment 목록 조회")
        status_ok, response = await test_endpoint(client, "/api/v1/resources/Deployment", 200, print_response=False)
        if status_ok and response:
            deployments = response.json()
            print(f"   📊 Deployment 수: {deployments.get('total', 0)}")
            for dep in deployments.get('resources', [])[:3]:  # 처음 3개만 표시
                name = dep.get('metadata', {}).get('name', 'Unknown')
                namespace = dep.get('metadata', {}).get('namespace', 'Unknown')
                print(f"   🚀 {name} ({namespace})")

        # 5. Service 목록 조회
        print("\n5. Service 목록 조회")
        status_ok, response = await test_endpoint(client, "/api/v1/resources/Service", 200, print_response=False)
        if status_ok and response:
            services = response.json()
            print(f"   📊 Service 수: {services.get('total', 0)}")
            for svc in services.get('resources', [])[:3]:  # 처음 3개만 표시
                name = svc.get('metadata', {}).get('name', 'Unknown')
                namespace = svc.get('metadata', {}).get('namespace', 'Unknown')
                print(f"   🌐 {name} ({namespace})")

        # 6. ConfigMap 목록 조회
        print("\n6. ConfigMap 목록 조회")
        status_ok, response = await test_endpoint(client, "/api/v1/resources/ConfigMap", 200, print_response=False)
        if status_ok and response:
            configmaps = response.json()
            print(f"   📊 ConfigMap 수: {configmaps.get('total', 0)}")
            for cm in configmaps.get('resources', [])[:3]:  # 처음 3개만 표시
                name = cm.get('metadata', {}).get('name', 'Unknown')
                namespace = cm.get('metadata', {}).get('namespace', 'Unknown')
                print(f"   ⚙️ {name} ({namespace})")

        # 7. Secret 목록 조회
        print("\n7. Secret 목록 조회")
        status_ok, response = await test_endpoint(client, "/api/v1/resources/Secret", 200, print_response=False)
        if status_ok and response:
            secrets = response.json()
            print(f"   📊 Secret 수: {secrets.get('total', 0)}")
            for secret in secrets.get('resources', [])[:3]:  # 처음 3개만 표시
                name = secret.get('metadata', {}).get('name', 'Unknown')
                namespace = secret.get('metadata', {}).get('namespace', 'Unknown')
                print(f"   🔐 {name} ({namespace})")

        # 8. 테스트 ConfigMap 생성 (실제 클러스터가 있는 경우)
        print("\n8. 테스트 ConfigMap 생성")
        test_configmap = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {
                "name": "test-configmap",
                "namespace": "default"
            },
            "data": {
                "test-key": "test-value",
                "environment": "test"
            }
        }
        
        status_ok, response = await test_endpoint(
            client, 
            "/api/v1/resources/ConfigMap", 
            200, 
            method="POST", 
            json_data=test_configmap,
            print_response=False
        )
        if status_ok and response:
            result = response.json()
            print(f"   ✅ ConfigMap 생성 성공: {result.get('name')}")
            
            # 생성된 ConfigMap 조회
            print("\n9. 생성된 ConfigMap 조회")
            status_ok, response = await test_endpoint(
                client, 
                f"/api/v1/resources/ConfigMap/test-configmap", 
                200,
                print_response=False
            )
            if status_ok and response:
                configmap = response.json()
                print(f"   📊 ConfigMap 상세 정보 조회 성공")
                print(f"   📋 데이터: {configmap.get('resource', {}).get('data', {})}")
            
            # 생성된 ConfigMap 삭제
            print("\n10. 생성된 ConfigMap 삭제")
            status_ok, response = await test_endpoint(
                client, 
                f"/api/v1/resources/ConfigMap/test-configmap", 
                200,
                method="DELETE",
                print_response=False
            )
            if status_ok and response:
                result = response.json()
                print(f"   ✅ ConfigMap 삭제 성공: {result.get('name')}")
        else:
            print(f"   ⚠️ ConfigMap 생성 실패 (Kubernetes 클러스터 연결 문제일 수 있음)")

    print("\n==================================================")
    print("🎉 Kubernetes API 테스트 완료!")

if __name__ == "__main__":
    asyncio.run(main())
