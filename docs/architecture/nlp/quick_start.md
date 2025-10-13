# NLP 시스템 퀵 스타트 가이드

> **목적**: NLP 시스템을 빠르게 시작하고 기본 명령어들을 테스트하는 방법을 설명하는 가이드

---

## 📋 목차
1. [시스템 요구사항](#시스템-요구사항)
2. [환경 설정](#환경-설정)
3. [서버 실행](#서버-실행)
4. [기본 명령어 테스트](#기본-명령어-테스트)
5. [고급 명령어 테스트](#고급-명령어-테스트)
6. [트러블슈팅](#트러블슈팅)

---

## 🎯 시스템 요구사항

### **필수 요구사항**
- Python 3.8+
- Kubernetes 클러스터 접근 권한
- Gemini API 키
- NKS kubeconfig 파일

### **권장 요구사항**
- Python 3.11+
- 최소 2GB RAM
- 안정적인 네트워크 연결

---

## 🔧 환경 설정

### **1. 가상환경 설정**
```bash
# 백엔드 디렉토리로 이동
cd backend-hybrid

# 가상환경 생성 및 활성화
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 또는
venv\Scripts\activate     # Windows

# 의존성 설치
pip install -r requirements.txt
```

### **2. 환경변수 설정**
```bash
# .env 파일 생성
cat > .env << EOF
# Gemini API 설정
GEMINI_API_KEY=your_gemini_api_key_here

# Kubernetes 설정
KLEPAAS_K8S_CONFIG_FILE=/path/to/your/nks-kubeconfig.yaml
KLEPAAS_K8S_CONTEXT=your_cluster_context

# 서버 설정
KLEPAAS_HOST=0.0.0.0
KLEPAAS_PORT=8000
KLEPAAS_DEBUG=true
EOF
```

### **3. Kubernetes 연결 테스트**
```bash
# kubeconfig 설정 확인
kubectl --kubeconfig ~/.kube/nks-*.yaml get nodes

# 네임스페이스 확인
kubectl --kubeconfig ~/.kube/nks-*.yaml get namespaces
```

---

## 🚀 서버 실행

### **1. 백엔드 서버 시작**
```bash
# 백엔드 디렉토리에서 실행
cd backend-hybrid

# 가상환경 활성화
source venv/bin/activate

# 서버 실행
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### **2. 서버 상태 확인**
```bash
# 헬스 체크
curl http://localhost:8000/health

# API 문서 확인
# 브라우저에서 http://localhost:8000/docs 접속
```

---

## 🧪 기본 명령어 테스트

### **1. 상태 확인 명령어**
```bash
# 기본 상태 확인
curl -X POST "http://localhost:8000/api/v1/nlp/process" \
     -H "Content-Type: application/json" \
     -d '{
       "command": "k-le-paas-test01-deploy 상태 확인해줘",
       "timestamp": "2025-10-13T11:20:00Z",
       "context": {"project_name": "test"}
     }'

# 다른 앱 상태 확인
curl -X POST "http://localhost:8000/api/v1/nlp/process" \
     -H "Content-Type: application/json" \
     -d '{
       "command": "nginx 상태 보여줘",
       "timestamp": "2025-10-13T11:20:00Z"
     }'
```

### **2. 로그 조회 명령어**
```bash
# 기본 로그 조회
curl -X POST "http://localhost:8000/api/v1/nlp/process" \
     -H "Content-Type: application/json" \
     -d '{
       "command": "k-le-paas-test01-deploy 로그 30줄 보여줘",
       "timestamp": "2025-10-13T11:20:00Z"
     }'

# 최대 로그 조회 (100줄)
curl -X POST "http://localhost:8000/api/v1/nlp/process" \
     -H "Content-Type: application/json" \
     -d '{
       "command": "k-le-paas-test01-deploy 최신 로그 100줄 보여줘",
       "timestamp": "2025-10-13T11:20:00Z"
     }'
```

### **3. 재시작 명령어**
```bash
# 앱 재시작
curl -X POST "http://localhost:8000/api/v1/nlp/process" \
     -H "Content-Type: application/json" \
     -d '{
       "command": "k-le-paas-test01-deploy 재시작해줘",
       "timestamp": "2025-10-13T11:20:00Z"
     }'

# 다른 표현으로 재시작
curl -X POST "http://localhost:8000/api/v1/nlp/process" \
     -H "Content-Type: application/json" \
     -d '{
       "command": "k-le-paas-test01-deploy 껐다 켜줘",
       "timestamp": "2025-10-13T11:20:00Z"
     }'
```

---

## 🔍 고급 명령어 테스트

### **1. 통합 대시보드 조회**
```bash
# 전체 상황 확인
curl -X POST "http://localhost:8000/api/v1/nlp/process" \
     -H "Content-Type: application/json" \
     -d '{
       "command": "전체 상황 보여줘",
       "timestamp": "2025-10-13T11:20:00Z"
     }'

# 대시보드 확인
curl -X POST "http://localhost:8000/api/v1/nlp/process" \
     -H "Content-Type: application/json" \
     -d '{
       "command": "대시보드 확인",
       "timestamp": "2025-10-13T11:20:00Z"
     }'
```

### **2. 리소스 목록 조회**
```bash
# 모든 파드 조회
curl -X POST "http://localhost:8000/api/v1/nlp/process" \
     -H "Content-Type: application/json" \
     -d '{
       "command": "모든 파드 조회해줘",
       "timestamp": "2025-10-13T11:20:00Z"
     }'

# 모든 Deployment 조회
curl -X POST "http://localhost:8000/api/v1/nlp/process" \
     -H "Content-Type: application/json" \
     -d '{
       "command": "모든 Deployment 조회해줘",
       "timestamp": "2025-10-13T11:20:00Z"
     }'

# 모든 Service 조회
curl -X POST "http://localhost:8000/api/v1/nlp/process" \
     -H "Content-Type: application/json" \
     -d '{
       "command": "모든 Service 조회해줘",
       "timestamp": "2025-10-13T11:20:00Z"
     }'

# 모든 도메인 조회
curl -X POST "http://localhost:8000/api/v1/nlp/process" \
     -H "Content-Type: application/json" \
     -d '{
       "command": "모든 도메인 조회해줘",
       "timestamp": "2025-10-13T11:20:00Z"
     }'

# 모든 네임스페이스 조회
curl -X POST "http://localhost:8000/api/v1/nlp/process" \
     -H "Content-Type: application/json" \
     -d '{
       "command": "모든 네임스페이스 조회해줘",
       "timestamp": "2025-10-13T11:20:00Z"
     }'
```

### **3. 엔드포인트 조회**
```bash
# 서비스 접속 주소 확인
curl -X POST "http://localhost:8000/api/v1/nlp/process" \
     -H "Content-Type: application/json" \
     -d '{
       "command": "nginx 접속 주소 알려줘",
       "timestamp": "2025-10-13T11:20:00Z"
     }'

# 다른 표현으로 엔드포인트 조회
curl -X POST "http://localhost:8000/api/v1/nlp/process" \
     -H "Content-Type: application/json" \
     -d '{
       "command": "nginx URL 확인",
       "timestamp": "2025-10-13T11:20:00Z"
     }'
```

### **4. 네임스페이스별 조회**
```bash
# 특정 네임스페이스 앱 목록
curl -X POST "http://localhost:8000/api/v1/nlp/process" \
     -H "Content-Type: application/json" \
     -d '{
       "command": "test 네임스페이스 앱 목록 보여줘",
       "timestamp": "2025-10-13T11:20:00Z"
     }'

# default 네임스페이스 전체 상황
curl -X POST "http://localhost:8000/api/v1/nlp/process" \
     -H "Content-Type: application/json" \
     -d '{
       "command": "default 네임스페이스 전체 현황",
       "timestamp": "2025-10-13T11:20:00Z"
     }'
```

---

## 🎯 예상 응답 예시

### **성공적인 응답**
```json
{
  "success": true,
  "message": "명령이 성공적으로 처리되었습니다.",
  "data": {
    "status": "success",
    "deployment": {
      "name": "k-le-paas-test01-deploy",
      "replicas": {
        "desired": 1,
        "current": 1,
        "ready": 1,
        "available": 1
      },
      "image": "nginx:1.21",
      "status": "Running"
    },
    "pods": [
      {
        "name": "k-le-paas-test01-deploy-xxx-1",
        "phase": "Running",
        "ready": "1/1",
        "restarts": 0
      }
    ]
  }
}
```

### **에러 응답**
```json
{
  "success": false,
  "message": "명령 처리 중 오류가 발생했습니다.",
  "error": "Deployment 'nonexistent-app'을 찾을 수 없습니다.",
  "data": {
    "status": "error",
    "message": "Deployment 'nonexistent-app'을 찾을 수 없습니다."
  }
}
```

---

## ⚠️ 트러블슈팅

### **1. 서버 시작 오류**
```bash
# 문제: ModuleNotFoundError
# 해결: 가상환경 활성화 확인
source venv/bin/activate
pip install -r requirements.txt

# 문제: 포트 이미 사용 중
# 해결: 다른 포트 사용
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

### **2. Kubernetes 연결 오류**
```bash
# 문제: kubeconfig 파일을 찾을 수 없음
# 해결: 환경변수 확인
echo $KLEPAAS_K8S_CONFIG_FILE
ls -la $KLEPAAS_K8S_CONFIG_FILE

# 문제: 권한 오류
# 해결: kubeconfig 권한 확인
kubectl --kubeconfig ~/.kube/nks-*.yaml auth can-i get pods
```

### **3. Gemini API 오류**
```bash
# 문제: API 키 오류
# 해결: 환경변수 확인
echo $GEMINI_API_KEY

# 문제: 네트워크 오류
# 해결: 인터넷 연결 및 방화벽 확인
curl -I https://generativelanguage.googleapis.com
```

### **4. 명령어 인식 오류**
```bash
# 문제: Gemini가 명령어를 인식하지 못함
# 해결: 더 구체적인 명령어 사용
# 나쁜 예: "상태"
# 좋은 예: "nginx 상태 확인해줘"

# 문제: 앱 이름을 찾을 수 없음
# 해결: 정확한 앱 이름 사용
kubectl --kubeconfig ~/.kube/nks-*.yaml get deployments
```

---

## 📚 추가 리소스

### **관련 문서**
- [NLP 구현 가이드](./implementation.md) - 상세한 구현 방법
- [NLP 실행 아키텍처](./execution.md) - 시스템 아키텍처
- [환경 설정 가이드](../../ENVIRONMENT_AND_CONFIG.md) - 상세한 환경 설정

### **유용한 명령어**
```bash
# 현재 실행 중인 파드 확인
kubectl --kubeconfig ~/.kube/nks-*.yaml get pods -o wide

# 서비스 목록 확인
kubectl --kubeconfig ~/.kube/nks-*.yaml get services

# Ingress 목록 확인
kubectl --kubeconfig ~/.kube/nks-*.yaml get ingresses

# 네임스페이스 목록 확인
kubectl --kubeconfig ~/.kube/nks-*.yaml get namespaces
```

---

## 🔄 업데이트 이력

| 버전 | 날짜 | 변경사항 |
|------|------|----------|
| 1.0.0 | 2025-10-12 | 초기 퀵 스타트 가이드 작성 |
| 2.0.0 | 2025-10-13 | 14개 명령어 테스트 가이드로 확장 |

---

**작성자**: AI Assistant  
**최종 수정**: 2025-10-13  
**다음 업데이트**: 새로운 명령어 추가 시

> **💡 팁**: 이 가이드를 따라하면 NLP 시스템의 모든 기본 기능을 테스트할 수 있습니다. 문제가 발생하면 트러블슈팅 섹션을 참고하세요!