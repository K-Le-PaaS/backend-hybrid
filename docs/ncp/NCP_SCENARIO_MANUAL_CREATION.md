# NCP SourceDeploy Scenario 수동 생성 가이드

> **배경 및 목적**: NCP SourceDeploy API를 통한 시나리오 자동 생성이 실패할 때 NCP Console에서 수동으로 시나리오를 생성하고 실제 API 페이로드를 캡처하여 정확한 스키마를 파악하기 위한 단계별 가이드입니다.

---

## 상황
- 자동 생성 실패: 에러 330900 "unknown"
- 프로젝트 ID: 12922 (API로 생성됨, 하지만 조회 안 됨)
- Stage ID: 14148 (production)
- Repository: K-Le-PaaS-test01 (ID: 634466, Project ID: 3067145)

## 단계별 가이드

### 1단계: NCP Console 접속
1. https://console.ncloud.com 접속
2. Services → DevTools → SourceDeploy 선택

### 2단계: 프로젝트 확인
1. 프로젝트 목록에서 `deploy-K-Le-PaaS-test01` 찾기
   - 있으면: ID가 12922인지 확인
   - 없으면: **새로 생성** (이름: `deploy-K-Le-PaaS-test01`)

### 3단계: Stage 확인
1. 프로젝트 클릭 → 상세 페이지
2. Stages 탭 확인
   - `production` Stage가 있는지 확인
   - 없으면: **새로 생성**
     - 이름: production
     - 배포 대상: NKS 클러스터 선택 (ID: 69b2edb8-2975-4cb4-9dcb-68e3902a68ec)

### 4단계: Scenario 생성하면서 API 캡처
1. **브라우저 개발자 도구 열기** (F12)
2. **Network 탭** 활성화
3. **Preserve log** 체크
4. **Scenario 생성** 버튼 클릭
5. 양식 작성:
   ```
   이름: deploy-app
   타입: Kubernetes
   배포 전략: Rolling Update 또는 Normal

   매니페스트 소스:
   - 타입: SourceCommit
   - 프로젝트: [선택 - 3067145 또는 DevTools 프로젝트명]
   - 리포지토리: K-Le-PaaS-test01
   - 브랜치: main
   - 경로: k8s/deployment.yaml
   ```
6. **생성 버튼 클릭**

### 5단계: API 요청 캡처
Network 탭에서:
1. POST 요청 찾기 (URL에 `/scenario` 포함)
2. **Request URL** 복사
3. **Request Headers** 복사
4. **Request Payload (Body)** 복사 ← **중요!**
5. Response 확인

### 6단계: 캡처한 정보 기록

캡처한 Request Payload를 아래에 붙여넣으세요:

```json
{
  // 여기에 실제 API 요청 body를 붙여넣기
}
```

## 성공 후 작업

Scenario가 성공적으로 생성되면:

1. **코드 업데이트**: `app/services/ncp_pipeline.py`의 시나리오 생성 body를 위에서 캡처한 payload로 수정
2. **테스트**: 다시 자동 생성 테스트
3. **문서화**: 정확한 스키마를 문서에 추가

## 대안: 수동 생성만 사용

Scenario 생성 자동화가 불가능하다면:

1. **모든 프로젝트에 대해 수동으로 Scenario 생성**
2. **코드는 기존 Scenario를 찾아서 사용하도록 수정**
   ```python
   # run_sourcedeploy에서 scenario 생성 로직 제거
   # 기존 scenario를 찾기만 함
   stage_id, scenario_id = await _get_stage_scenario_ids()
   if not scenario_id:
       raise HTTPException(400, detail="Scenario not found. Create manually first.")
   ```

## 참고사항

### 왜 자동 생성이 실패하는가?

1. **프로젝트 생성 문제**
   - API가 200 OK 반환
   - 하지만 GET /project/{id}는 404 반환
   - 프로젝트가 실제로 생성되지 않았을 가능성

2. **Target 설정 불가**
   - PUT /project/{id}/stage/{id}/target → 404
   - 이 API 엔드포인트가 존재하지 않음
   - Stage 생성 시 target을 포함해도 무시됨

3. **Scenario 생성 스키마 불일치**
   - 에러 330900 "unknown"
   - 시도한 모든 스키마 변형이 실패
   - NCP가 기대하는 정확한 스키마를 모름

### 해결 방법

**유일한 해결책: NCP Console에서 수동 생성 시 실제 API 페이로드 캡처**

이것이 NCP API의 정확한 스키마를 알 수 있는 유일한 방법입니다.

---

**관련 문서**:
- [NCP 시나리오 디버깅](./NCP_SCENARIO_DEBUG.md)
- [NCP 이미지 이름 수정](./NCP_IMAGE_NAME_FIX.md)

