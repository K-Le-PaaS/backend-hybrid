# NCP SourceBuild Image Name with Timestamp for Uniqueness

> **배경 및 목적**: 여러 사용자가 동일한 리포지토리 이름을 사용할 때 이미지 이름 충돌을 방지하기 위해 프로젝트 생성 시 밀리초 타임스탬프를 이미지 이름에 추가하여 고유성을 보장합니다.

---

## 설계 목표

이미지 이름 충돌 방지를 위한 타임스탬프 기반 고유 이미지 이름 생성 전략:

- **형식**: `{repository_name}{timestamp_milliseconds}`
- **예시**: Repository `test-01`을 `1760028730123` 시점에 생성 → Image name `test011760028730123`
- **NCR 규격 준수**: NCR이 허용하지 않는 `-` 및 `_` 문자 제거

## 구현 전략

1. **프로젝트 생성**: 타임스탬프가 포함된 고유 이미지 이름 생성 (예: `test011760028730123`)
2. **빌드 실행**: 프로젝트 캐시 설정에서 동일한 이미지 이름 사용
3. **NCR 푸시**: NCP가 프로젝트 설정의 이미지 이름으로 푸시
4. **검증**: 동일한 타임스탬프 이름으로 확인

이 방식의 장점:
- ✅ **고유성**: 타임스탬프로 충돌 방지 보장
- ✅ **일관성**: 프로젝트와 빌드가 동일한 이름 사용
- ✅ **NCR 규격 준수**: 유효하지 않은 문자(-, _) 제거
- ✅ **추적성**: 타임스탬프로 프로젝트 생성 시점 확인

## 솔루션

`app/services/ncp_pipeline.py`를 수정하여 프로젝트의 캐시 설정에서 이미지 이름을 추출하고 빌드 실행 플로우 전체에서 일관되게 사용합니다.

### 변경사항

#### 1. 프로젝트 생성 시 고유 이미지 이름 생성 (lines 318-323)

```python
# Make image name unique with timestamp (milliseconds) to avoid conflicts
# Remove - and _ from image name as NCR doesn't allow them
import time
safe_image_name = image_name.replace('-', '').replace('_', '')
timestamp_ms = int(time.time() * 1000)
unique_image_name = f"{safe_image_name}{timestamp_ms}"

# Use in project cache config
body = {
    ...
    "cache": {
        "use": True,
        "registry": registry_project,
        "image": unique_image_name,  # e.g., test011760028730123
        "tag": "latest",
        "latest": True,
        "region": 1
    },
    ...
}
```

#### 2. 프로젝트 캐시 설정에서 이미지 이름 추출 (lines 1387-1407)

```python
# Extract cache config from project to ensure consistency with project creation
registry_project: str | None = None
image_name_from_project: str | None = None
image_tag: str = 'latest'
try:
    proj_detail = await _call_ncp_rest_api('GET', base, f"/api/v1/project/{build_project_id}")
    proj_result = proj_detail.get('result', {}) if isinstance(proj_detail, dict) else {}
    cache_cfg = (proj_result.get('cache') or {}) if isinstance(proj_result, dict) else {}
    registry_project = cache_cfg.get('registry') or None
    image_name_from_project = cache_cfg.get('image') or None
    image_tag = cache_cfg.get('tag') or image_tag
    _dbg("SB-PROJECT-CONFIG", registry=registry_project, image=image_name_from_project,
         tag=image_tag, cache_config=json.dumps(cache_cfg, ensure_ascii=False)[:200])
except Exception as e:
    _dbg("SB-PROJECT-CONFIG-ERR", error=str(e)[:200])
```

#### 3. 프로젝트에서 직접 이미지 이름 사용 (lines 1420-1428)

```python
# Use image name directly from project cache config (already has timestamp for uniqueness)
if image_name_from_project:
    # Project cache config has image name with timestamp (created at project creation time)
    # No need to append anything - the timestamp already ensures uniqueness
    final_image_name = image_name_from_project
    final_registry_project = registry_project or "klepaas-test"
    _dbg("SB-IMAGE-SOURCE", source="project_cache_config",
         image=final_image_name,
         registry=final_registry_project)
else:
    # Fallback: Derive from image_repo parameter
    final_image_name = image_path.rsplit("/", 1)[-1]
    final_registry_project = (registry_host or "").split(".")[0] or "klepaas-test"

# Use cache block with timestamped image name from project
trigger_body = {
    "cache": {
        "use": True,
        "registry": final_registry_project,
        "image": final_image_name,  # Already has timestamp
        "tag": image_tag,
        "latest": (image_tag == "latest")
    }
}
```

#### 4. Fallback 이미지 경로 구성 업데이트 (lines 1481-1494, 1563-1576)

```python
if not container_image:
    # Construct image path using project cache config for consistency
    if final_registry_project and final_image_name:
        container_image = f"{final_registry_project}.kr.ncr.ntruss.com/{final_registry_project}/{final_image_name}:{image_tag}"
        image_source = "project_cache_fallback"
        _dbg("SB-IMAGE-FALLBACK", source="project_cache", image=container_image)
    elif image_repo:
        # Second fallback: use image_repo parameter
        container_image = f"{image_repo}:{image_tag}"
        image_source = "image_repo_fallback"
```

## 예상 결과

이러한 변경으로 `test-01` 리포지토리를 타임스탬프 `1760028730123`에 생성하면:

1. **프로젝트 생성**: 캐시 설정에 타임스탬프가 포함된 이미지 이름 `test011760028730123` 생성
2. **트리거 바디** 전송: `{"cache": {"image": "test011760028730123", ...}}`
3. **NCP 빌드 및 푸시**: NCR에 `klepaas-test/test011760028730123:latest` 푸시
4. **코드 검증**: NCR 매니페스트 API에서 `klepaas-test.kr.ncr.ntruss.com/test011760028730123:latest` 확인
5. **일관된 이름 사용**: 모든 곳에서 `test011760028730123` 사용

이를 통해 다음이 보장됩니다:
- ✅ **고유성**: 밀리초 타임스탬프로 충돌 방지
- ✅ **일관성**: 프로젝트, 빌드 트리거, NCR 푸시, 검증 모두 동일한 이름 사용
- ✅ **NCR 규격 준수**: 유효하지 않은 문자(-, _) 제거
- ✅ **추적성**: 타임스탬프로 프로젝트 생성 시점 확인

## 테스트

이러한 변경 후 예상되는 로그:

```
[SB-PROJECT-CONFIG] cache={"use": true, "registry": "klepaas-test", "image": "test011760028730123", ...}
[SB-IMAGE-SOURCE] source=project_cache_config, image=test011760028730123, registry=klepaas-test
[SB-TRIGGER-BODY] body={'cache': {'use': True, 'registry': 'klepaas-test', 'image': 'test011760028730123', ...}}
[SB-BUILD-SUCCESS] build_id=..., image=klepaas-test.kr.ncr.ntruss.com/test011760028730123:latest, registry_verified=True
[NCR-VERIFY] attempt=1, code=200, verified=True
```

## 관련 파일

- `app/services/ncp_pipeline.py`: 주요 변경사항 (프로젝트 설정 추출, 트리거 바디, 폴백 경로)
- `app/services/ncp_pipeline.py` (`create_sourcebuild_project_rest`): 이미 올바름 - 깨끗한 이미지 이름으로 캐시 설정 사용

## 이전 이슈 해결

이 수정은 이전에 해결된 여러 이슈를 기반으로 합니다:

1. **NCR 매니페스트 경로 구성**: 프로젝트 포함 전체 경로가 아닌 이미지 이름만 사용하도록 수정
2. **NCR 전파 지연**: 재시도 지연을 120초로 확장
3. **빌드 실행**: 실제 Docker 빌드를 트리거하기 위해 `artifact`에서 `cache` 블록으로 변경
4. **프로젝트 생성**: `artifact` 대신 `cache` 구성을 사용하도록 업데이트

---

**관련 문서**:
- [NCP 시나리오 디버깅](./NCP_SCENARIO_DEBUG.md)
- [NCP 시나리오 수동 생성 가이드](./NCP_SCENARIO_MANUAL_CREATION.md)

