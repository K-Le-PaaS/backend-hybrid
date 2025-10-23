# Deployment History Duplication Analysis

## Summary

The deployment history system has two critical issues:

1. **Kubernetes Watcher Disabled**: The update mechanism that should convert "running" → "success" is completely disabled
2. **Duplicate Record Creation**: Each deployment creates duplicate records with identical timestamps

## Issue 1: Disabled Update Mechanism

### Location
`app/services/kubernetes_watcher.py:655-668`

### Problem
The `update_deployment_history_on_success` function is completely disabled:

```python
async def update_deployment_history_on_success(event_data: Dict[str, Any]) -> None:
    """
    K8s Deployment 성공 시 deployment_histories의 deployed_at을 업데이트합니다.

    임시로 큐 시스템을 비활성화하고 직접 처리합니다.
    """
    # 임시로 아무 작업도 하지 않음 (DB 락 문제로 인해)
    logger.debug(
        "deployment_history_update_skipped",
        deployment=event_data.get("name"),
        namespace=event_data.get("namespace"),
        reason="db_lock_issue"
    )
    return  # ← Early return! Function does nothing!
```

### Original Intent
Lines 554-557 show the intended UPDATE logic:
```python
history.status = "success"
history.sourcedeploy_status = "success"
history.deployed_at = now
history.completed_at = now
```

### Why Disabled
Comment says: "DB 락 문제로 인해" (due to DB lock issue) - **THIS IS THE SAME SQLITE LOCK ISSUE WE JUST FIXED WITH WAL MODE!**

## Issue 2: Duplicate Records

### Evidence from Database
```
Commit 559ec56:
  ID=14: status=success, rollback=0, created=2025-01-20 10:11:46, deployed=None
  ID=15: status=running, rollback=0, created=2025-01-20 10:11:46, deployed=None
```

**Both records have IDENTICAL created_at timestamps!**

### Current Flow
1. `ncp_pipeline.py:2557-2583` - Creates DeploymentHistory with `status="running"`
2. **Something unknown** - Creates duplicate record with `status="success"` at same timestamp
3. Kubernetes watcher - **DISABLED** (should update running → success, but doesn't)

### Result
- 16 total deployment records
- 11 stuck in "running" status (69%)
- 5 marked as "success" but with NULL deployed_at
- All deployed_at fields are NULL (update never happens)

## Root Causes

### 1. SQLite Lock Issue (NOW FIXED)
The kubernetes_watcher was disabled to avoid SQLite database locks. We fixed this with:
- WAL mode enabled in `database.py`
- Transaction commits in `rollback.py`
- Proper session cleanup in `commands.py`

### 2. Disabled Watcher
After fixing DB locks, the watcher was never re-enabled. It still has early return.

### 3. Unknown Duplicate Creation
Cannot identify source of second "success" record creation. Possibilities:
- Webhook callback creating duplicate
- Event handler firing twice
- Race condition in deployment flow
- Legacy code path still active

## Recommended Fixes

### Priority 1: Re-enable Kubernetes Watcher
Since SQLite WAL mode is now active and DB locks are resolved:

```python
# app/services/kubernetes_watcher.py:655-668
async def update_deployment_history_on_success(event_data: Dict[str, Any]) -> None:
    """
    K8s Deployment 성공 시 deployment_histories의 deployed_at을 업데이트합니다.
    """
    # REMOVE THE EARLY RETURN
    # Re-enable the actual update logic (lines ~520-580)
```

### Priority 2: Add Unique Constraint
Prevent duplicate records at database level:

```python
# app/models/deployment_history.py
__table_args__ = (
    UniqueConstraint(
        'github_owner', 'github_repo', 'github_commit_sha', 'created_at',
        name='uq_deployment_per_commit'
    ),
)
```

### Priority 3: Find Duplicate Source
Add logging to track where "success" records are created:

```python
# In ncp_pipeline.py after line 2580 (db.add(history_record))
logger.info(
    "deployment_history_created",
    id=deploy_history_id,
    status="running",
    commit_sha=effective_tag,
    stack_trace=traceback.format_stack()[-3:]  # Log caller
)
```

## Testing Plan

1. **Re-enable watcher** in kubernetes_watcher.py
2. **Deploy test commit** and monitor logs
3. **Verify single record** created with status progression: running → success
4. **Verify deployed_at** gets populated correctly
5. **Check for duplicates** in database

## Data Cleanup

After fixes are deployed, clean up existing data:

```sql
-- Find and keep only the latest record per commit
WITH ranked_deployments AS (
    SELECT
        id,
        ROW_NUMBER() OVER (
            PARTITION BY github_owner, github_repo, github_commit_sha
            ORDER BY id DESC
        ) as rn
    FROM deployment_histories
)
DELETE FROM deployment_histories
WHERE id IN (
    SELECT id FROM ranked_deployments WHERE rn > 1
);

-- Update remaining running records to success if deployment actually succeeded
UPDATE deployment_histories
SET status = 'success',
    deployed_at = created_at  -- Use created_at as estimate
WHERE status = 'running'
  AND created_at < datetime('now', '-10 minutes');  -- Only old records
```
