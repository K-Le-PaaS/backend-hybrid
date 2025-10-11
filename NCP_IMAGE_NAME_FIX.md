# NCP SourceBuild Image Name with Timestamp for Uniqueness

## Design Goal

To prevent image name conflicts when multiple users have repositories with the same name, we append a millisecond timestamp to the image name at project creation time:

- **Format**: `{repository_name}{timestamp_milliseconds}`
- **Example**: Repository `test-01` created at `1760028730123` → Image name `test011760028730123`
- **NCR Compliance**: Removes `-` and `_` from repository name as NCR doesn't allow them

## Implementation Strategy

1. **Project creation**: Generate unique image name with timestamp (e.g., `test011760028730123`)
2. **Build execution**: Use the same image name from project cache config
3. **NCR push**: NCP pushes with the image name from project configuration
4. **Verification**: Check using the same timestamped name

This ensures:
- ✅ **Uniqueness**: Timestamp guarantees no conflicts across users
- ✅ **Consistency**: Project and build use the same name
- ✅ **NCR Compliance**: Removes invalid characters (- and _)
- ✅ **Traceability**: Timestamp shows when project was created

## Solution

Modified `app/services/ncp_pipeline.py` to extract the image name from the project's cache configuration and use it consistently throughout the build execution flow.

### Changes Made

#### 1. Generate Unique Image Name at Project Creation (lines 318-323)

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

#### 2. Extract Image Name from Project Cache Config (lines 1387-1407)

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

#### 3. Use Image Name Directly from Project (lines 1420-1428)

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

#### 4. Update Fallback Image Path Construction (lines 1481-1494, 1563-1576)

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

## Expected Outcome

With these changes, for repository `test-01` created at timestamp `1760028730123`:

1. **Project creation**: Creates with timestamped image name `test011760028730123` in cache config
2. **Trigger body** sends: `{"cache": {"image": "test011760028730123", ...}}`
3. **NCP builds and pushes**: `klepaas-test/test011760028730123:latest` to NCR
4. **Code verifies**: `klepaas-test.kr.ncr.ntruss.com/test011760028730123:latest` in NCR manifest API
5. **All use consistent naming**: `test011760028730123` (same everywhere)

This ensures:
- ✅ **Uniqueness**: Millisecond timestamp guarantees no conflicts
- ✅ **Consistency**: Project, build trigger, NCR push, and verification all use same name
- ✅ **NCR Compliance**: Invalid characters (-, _) are removed
- ✅ **Traceability**: Timestamp shows when project was created

## Testing

After these changes, the expected logs should show:

```
[SB-PROJECT-CONFIG] cache={"use": true, "registry": "klepaas-test", "image": "test011760028730123", ...}
[SB-IMAGE-SOURCE] source=project_cache_config, image=test011760028730123, registry=klepaas-test
[SB-TRIGGER-BODY] body={'cache': {'use': True, 'registry': 'klepaas-test', 'image': 'test011760028730123', ...}}
[SB-BUILD-SUCCESS] build_id=..., image=klepaas-test.kr.ncr.ntruss.com/test011760028730123:latest, registry_verified=True
[NCR-VERIFY] attempt=1, code=200, verified=True
```

## Related Files

- `app/services/ncp_pipeline.py`: Main changes (project config extraction, trigger body, fallback paths)
- `app/services/ncp_pipeline.py` (`create_sourcebuild_project_rest`): Already correct - uses cache config with clean image name

## Previous Issues Resolved

This fix builds upon several previous issues that were also resolved:

1. **NCR manifest path construction**: Fixed to use only image name, not full path with project
2. **NCR propagation delays**: Extended retry delays to 120 seconds
3. **Build execution**: Changed from `artifact` to `cache` block to trigger actual Docker builds
4. **Project creation**: Updated to use `cache` configuration instead of `artifact`
