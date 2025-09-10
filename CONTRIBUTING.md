## 🌱 브랜치 전략

- **main**: 프로덕션용 배포 브랜치, 직접 커밋 금지 / PR만 병합
- **develop**: 기능 개발 통합 브랜치
- **feature/***: 새로운 기능 작업 브랜치 (develop에서 분기)
- **hotfix/***: 긴급 버그 수정 브랜치 (main에서 분기, 완료 시 main/develop 병합)
- **release/***: 릴리즈 준비 브랜치 (develop에서 분기)

## 📍 브랜치 컨벤션

| **브랜치 유형** | **규칙 예시**                     |
|------------|-------------------------------|
| main       | `main`                        |
| develop    | `develop`                     |
| feature    | `feature/#3-user-post-api`    |
| fix        | `fix/#12-schedule-get-api`    |
| release    | `release/1.0.0`               |
| hotfix     | `hotfix/#20-login-expire-fix` |

## 💬 커밋 메시지 컨벤션
- 형식: `[태그] 커밋 내용`
- 태그는 **영문 대문자**로 작성합니다.

| **태그** | **설명** |
| --- | --- |
| FEAT | 새로운 기능 추가 |
| FIX | 버그 수정 |
| CHORE | 기타 자잘한 수정 (빌드, 설정 등) |
| DOCS | 문서 수정 (README, 주석 등) |
| INIT | 초기 설정 (프로젝트 초기 구조 세팅) |
| TEST | 테스트 코드 추가 / 수정 |
| RENAME | 파일, 폴더명 변경 |
| STYLE | 코드 포맷팅, 세미콜론, 코드 변화 없음 |
| REFACTOR | 코드 리팩토링 (기능 변화 없음) |

**✅ 예시**

- [FEAT] 명령어 API 추가
- [FIX] Redis 연결 오류 해결
- [REFACTOR] JWT 필터 구조 개선

## 🛠 PR 가이드

- PR은 대상 브랜치에 맞춰 생성할 것 (feature → develop, hotfix/release → main)
- 반드시 적절한 리뷰어를 지정하고 리뷰 반영 후 병합
- PR 템플릿을 따라 상세 설명 작성

## 📚 기타

- 코드 스타일 및 포맷팅 도구(예: Prettier, ESLint)를 사용
- 작성한 코드는 반드시 테스트 커버리지 포함
