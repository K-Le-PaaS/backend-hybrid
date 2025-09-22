# 고급 자연어 처리 (Advanced NLP) 가이드

## 개요

K-Le-PaaS v6의 고급 자연어 처리 시스템은 다중 AI 모델, 컨텍스트 인식, 지능적 해석, 학습 기반 개선을 통합한 차세대 자연어 처리 엔진입니다.

## 주요 기능

### 1. 다중 AI 모델 통합
- **Claude 3.5 Sonnet**: 고급 추론 및 창의적 해석
- **GPT-4**: 정확한 구조화된 응답
- **Gemini 2.0 Flash**: 빠른 처리 및 다국어 지원
- **자동 모델 선택**: 신뢰도 및 성능 기반 최적 모델 선택

### 2. 컨텍스트 인식 처리
- **대화 히스토리 추적**: Redis 기반 대화 컨텍스트 관리
- **프로젝트 상태 인식**: 현재 배포 상태 및 설정 파악
- **사용자 패턴 학습**: 개인화된 명령 해석

### 3. 지능적 명령 해석
- **모호함 감지**: 불명확한 명령 자동 감지
- **자동 수정 제안**: 문법 및 의미 오류 자동 수정
- **대안 제시**: 여러 해석 가능성 제시

### 4. 학습 기반 개선
- **사용자 피드백 학습**: 사용자 수정사항 학습
- **성공 패턴 분석**: 성공적인 명령 패턴 학습
- **모델 성능 추적**: 각 모델의 성능 지속 모니터링

## 아키텍처

```
사용자 명령
    ↓
GeminiClient (진입점)
    ↓
AdvancedNLPService (통합 서비스)
    ↓
├── MultiModelProcessor (다중 모델 처리)
├── ContextManager (컨텍스트 관리)
├── SmartCommandInterpreter (지능적 해석)
└── LearningProcessor (학습 처리)
    ↓
MCP 도구 호출
```

## 설정

### 환경 변수

```bash
# 고급 NLP 활성화
KLEPAAS_ADVANCED_NLP_ENABLED=true

# Redis 설정
KLEPAAS_REDIS_URL=redis://localhost:6379

# AI 모델 API 키
KLEPAAS_CLAUDE_API_KEY=your_claude_key
KLEPAAS_OPENAI_API_KEY=your_openai_key
KLEPAAS_GEMINI_API_KEY=your_gemini_key

# 모델 선택 전략
KLEPAAS_MODEL_SELECTION_STRATEGY=confidence_based  # confidence_based, performance_based, hybrid

# 신뢰도 임계값
KLEPAAS_CONFIDENCE_THRESHOLD=0.7

# 컨텍스트 설정
KLEPAAS_MAX_CONTEXT_LENGTH=4000
KLEPAAS_CONTEXT_WINDOW_SIZE=10
```

### 설정 파일 (config.py)

```python
# 고급 NLP 설정
advanced_nlp_enabled: bool = True
redis_url: str = "redis://localhost:6379"
context_ttl: int = 3600  # 컨텍스트 TTL (초)
conversation_ttl: int = 86400  # 대화 히스토리 TTL (초)

# 다중 모델 설정
multi_model_enabled: bool = True
model_selection_strategy: str = "confidence_based"
confidence_threshold: float = 0.7

# 학습 설정
learning_enabled: bool = True
feedback_learning_rate: float = 0.1
pattern_learning_rate: float = 0.05
```

## 사용법

### 1. 기본 사용법

```python
from app.llm.gemini import GeminiClient

# Gemini 클라이언트 초기화
client = GeminiClient()

# 자연어 명령 해석
result = await client.interpret(
    prompt="myapp을 스테이징에 배포해줘",
    user_id="user123",
    project_name="my-project"
)

print(f"의도: {result['intent']}")
print(f"메시지: {result['message']}")
print(f"고급 NLP 결과: {result.get('advanced_nlp', {})}")
```

### 2. 고급 NLP 서비스 직접 사용

```python
from app.llm.advanced_nlp_service import AdvancedNLPService

# 서비스 초기화
service = AdvancedNLPService()
await service.initialize()

# 고급 명령 처리
result = await service.process_command(
    user_id="user123",
    project_name="my-project",
    command="앱을 배포해줘",
    context={"current_deployments": [{"name": "my-web-app"}]}
)

print(f"신뢰도: {result['confidence']:.2f}")
print(f"사용된 모델: {result['best_model']}")
print(f"모호함: {len(result['ambiguities'])}개")
print(f"제안: {len(result['suggestions'])}개")
```

### 3. 피드백 학습

```python
# 사용자 피드백 기록
await service.record_feedback(
    user_id="user123",
    command="앱을 배포해줘",
    original_interpretation=result["interpreted_command"],
    user_correction={
        "action": "deploy",
        "target": "my-web-app",
        "environment": "staging"
    },
    feedback_type="correction",
    success=True
)
```

### 4. 사용자 인사이트 조회

```python
# 사용자 인사이트 조회
insights = await service.get_user_insights("user123")

print(f"최근 대화: {insights['recent_conversations']}개")
print(f"성공률: {insights['user_pattern']['success_rate']:.1%}")
print(f"학습된 제안: {len(insights['learned_suggestions'])}개")
```

## API 참조

### GeminiClient

#### `interpret(prompt, user_id, project_name)`
자연어 명령을 해석하고 적절한 MCP 도구를 호출합니다.

**매개변수:**
- `prompt` (str): 자연어 명령
- `user_id` (str): 사용자 ID
- `project_name` (str): 프로젝트 이름

**반환값:**
```python
{
    "intent": "deploy",
    "entities": {"app_name": "myapp", "environment": "staging"},
    "result": {...},  # MCP 도구 실행 결과
    "message": "고급 배포 명령이 성공적으로 처리되었습니다",
    "advanced_nlp": {
        "confidence": 0.85,
        "best_model": "claude-3.5-sonnet",
        "suggestions": [...],
        "ambiguities": [...]
    },
    "llm": {
        "provider": "gemini_advanced",
        "mode": "advanced_deploy"
    }
}
```

### AdvancedNLPService

#### `process_command(user_id, project_name, command, context)`
고급 명령 처리를 수행합니다.

**매개변수:**
- `user_id` (str): 사용자 ID
- `project_name` (str): 프로젝트 이름
- `command` (str): 자연어 명령
- `context` (dict, optional): 추가 컨텍스트

**반환값:**
```python
{
    "original_command": "앱을 배포해줘",
    "interpreted_command": {
        "action": "deploy",
        "entities": {...}
    },
    "confidence": 0.85,
    "quality": "high",
    "best_model": "claude-3.5-sonnet",
    "model_responses": [...],
    "ambiguities": [...],
    "suggestions": [...],
    "learned_suggestions": [...],
    "alternatives": [...],
    "context": {...},
    "processing_metadata": {...}
}
```

#### `record_feedback(user_id, command, original_interpretation, user_correction, feedback_type, success)`
사용자 피드백을 기록합니다.

#### `get_user_insights(user_id)`
사용자 인사이트를 조회합니다.

## 테스트

### 통합 테스트 실행

```bash
# 고급 NLP 통합 테스트 실행
python test_advanced_nlp_integration.py
```

### 테스트 항목

1. **기본 Gemini 통합 테스트**
   - 배포, 롤백, 모니터링, 스케일링 명령 테스트
   - MCP 도구 호출 검증

2. **고급 NLP 처리 테스트**
   - 다중 모델 처리 검증
   - 컨텍스트 인식 처리 검증
   - 지능적 해석 검증

3. **피드백 학습 테스트**
   - 사용자 피드백 기록 검증
   - 학습 데이터 저장 검증

4. **사용자 인사이트 테스트**
   - 사용자 패턴 분석 검증
   - 학습된 제안 조회 검증

5. **오류 처리 테스트**
   - 잘못된 입력 처리 검증
   - 예외 상황 처리 검증

## 성능 최적화

### 1. Redis 캐싱
- 컨텍스트 데이터 Redis 캐싱
- 대화 히스토리 TTL 설정
- 패턴 데이터 지속적 캐싱

### 2. 모델 선택 최적화
- 신뢰도 기반 모델 선택
- 성능 기반 모델 선택
- 하이브리드 선택 전략

### 3. 비동기 처리
- 모든 AI 모델 호출 비동기 처리
- 병렬 모델 응답 처리
- 비동기 컨텍스트 관리

## 모니터링

### 1. 성능 지표
- 모델별 응답 시간
- 신뢰도 분포
- 성공률 추적

### 2. 로깅
- 구조화된 로깅
- 모델 선택 로그
- 오류 추적

### 3. 알림
- 모델 성능 저하 알림
- 오류율 증가 알림
- 학습 데이터 품질 알림

## 문제 해결

### 1. 일반적인 문제

**Q: 고급 NLP가 작동하지 않아요**
A: `KLEPAAS_ADVANCED_NLP_ENABLED=true` 설정을 확인하고 Redis 연결을 확인하세요.

**Q: 모델 응답이 느려요**
A: Redis 캐싱 설정을 확인하고 모델 선택 전략을 `performance_based`로 변경해보세요.

**Q: 학습이 제대로 되지 않아요**
A: 피드백 데이터가 올바르게 기록되고 있는지 확인하고 학습 가중치 설정을 조정해보세요.

### 2. 디버깅

```python
# 디버그 모드 활성화
import logging
logging.getLogger("app.llm").setLevel(logging.DEBUG)

# 상세 로그 확인
logger = logging.getLogger("app.llm.advanced_nlp_service")
logger.debug("고급 NLP 처리 상세 로그")
```

## 향후 계획

1. **더 많은 AI 모델 지원**
   - Llama 3, Mistral 등 오픈소스 모델 추가
   - 로컬 모델 지원

2. **고급 기능**
   - 멀티모달 처리 (이미지, 음성)
   - 실시간 학습
   - 자동 모델 튜닝

3. **성능 개선**
   - 모델 앙상블
   - 지연 시간 최적화
   - 메모리 사용량 최적화

## 참고 자료

- [FastMCP 문서](https://github.com/jlowin/fastmcp)
- [Google GenAI Python SDK](https://github.com/googleapis/python-genai)
- [Anthropic Claude API](https://docs.anthropic.com/)
- [OpenAI API](https://platform.openai.com/docs)