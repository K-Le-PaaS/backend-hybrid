# NCP SourceDeploy Scenario 생성 디버깅 가이드

## 문제 상황
- Deploy 프로젝트: **12920** ✅ 생성 성공
- Stage: **14146** (production) ✅ 생성 성공
- Scenario: ❌ **생성 실패** (에러 330900 "unknown")

## 로그 분석
```
deploy_project_id=12920
stage_id=14146
sc_project_id=3067145
sc_repo_name=K-Le-PaaS-test01
sc_repo_id=634466
```

모든 시나리오 생성 시도가 실패:
```json
{
  "error": {
    "errorCode": 330900,
    "message": "unknown",
    "details": ""
  }
}
```

## 시도한 페이로드들

### 1. Golden Payload (실패)
```json
{
  "name": "deploy-app",
  "description": "Auto-generated Kubernetes deployment",
  "type": "KUBERNETES",
  "config": {
    "strategy": "rolling",
    "manifest": {
      "type": "SourceCommit",
      "path": "k8s/deployment.yaml",
      "branch": "main",
      "repository": {
        "name": "K-Le-PaaS-test01",
        "projectId": 3067145
      }
    }
  }
}
```

### 2. Top-level variant (실패)
```json
{
  "name": "deploy-app",
  "type": "KUBERNETES",
  "config": {
    "strategy": "normal",
    "manifest": {
      "type": "SourceCommit",
      "path": "k8s/deployment.yaml",
      "branch": "main",
      "repository": {
        "name": "K-Le-PaaS-test01",
        "projectId": 3067145
      }
    }
  }
}
```

### 3. Repository ID variant (실패)
```json
{
  "name": "deploy-app",
  "description": "Auto-generated Kubernetes deployment",
  "config": {
    "strategy": "normal",
    "manifest": {
      "type": "SourceCommit",
      "repositoryId": 634466,
      "branch": "main",
      "path": ["k8s/deployment.yaml", "k8s/service.yaml"]
    }
  }
}
```

### 4. Inline manifest (실패)
```json
{
  "name": "deploy-app",
  "description": "Auto-generated Kubernetes deployment (inline)",
  "config": {
    "strategy": "normal",
    "manifest": {
      "type": "Inline",
      "files": [
        {"type": "TEXT", "path": "deployment.yaml", "content": "..."},
        {"type": "TEXT", "path": "service.yaml", "content": "..."}
      ]
    }
  }
}
```

## 해결 방법

### 옵션 1: NCP Console에서 수동 생성 후 API 페이로드 확인

1. **NCP Console 접속**
   - https://console.ncloud.com
   - SourceDeploy > 프로젝트 목록에서 `deploy-K-Le-PaaS-test01` (ID: 12920) 찾기

2. **수동으로 시나리오 생성**
   - Stage: production (ID: 14146)
   - 시나리오 이름: deploy-app
   - 타입: Kubernetes
   - 매니페스트: SourceCommit
   - 리포지토리: K-Le-PaaS-test01
   - 브랜치: main
   - 경로: k8s/deployment.yaml

3. **브라우저 Network Tab에서 요청 확인**
   - F12 개발자 도구
   - Network 탭
   - 시나리오 생성 버튼 클릭
   - POST 요청 찾기
   - Request Payload 복사

### 옵션 2: NCP API 문서 확인

NCP SourceDeploy API 공식 문서에서 정확한 스키마 확인:
- https://api.ncloud-docs.com/docs/devtools-sourcedeploy

### 옵션 3: NCP 지원팀 문의

에러 코드 330900이 "unknown"이므로 NCP 지원팀에 문의:
- 프로젝트 ID: 12920
- Stage ID: 14146
- 에러 코드: 330900
- 시도한 페이로드들 첨부

## 임시 해결책

당분간은 **NCP Console에서 수동으로 시나리오를 생성**하고,
코드에서는 기존 시나리오를 찾아서 사용하는 방식으로 우회:

```python
# run_sourcedeploy 함수에서
# 시나리오 생성을 건너뛰고 기존 시나리오를 찾기만 함
stage_id, scenario_id = await _get_stage_scenario_ids()
if not scenario_id:
    raise HTTPException(
        status_code=400,
        detail="Scenario not found. Please create it manually in NCP Console first."
    )
```

## 다음 단계

1. [ ] NCP Console에서 수동 생성 시 Network 요청 캡처
2. [ ] 정확한 API 페이로드 스키마 확인
3. [ ] 코드 수정 및 테스트
4. [ ] 또는 NCP 지원팀 문의
