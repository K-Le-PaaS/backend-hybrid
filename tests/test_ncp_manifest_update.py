"""
Test suite for NCP SourceCommit manifest update functionality.

Tests the improved manifest update logic with:
- YAML partial updates (preserving existing structure)
- Image registry verification
- Mandatory update enforcement
- Error handling
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException

from app.services.ncp_pipeline import (
    update_sourcecommit_manifest,
    _generate_default_manifest,
    _verify_ncr_manifest_exists,
)


class TestManifestUpdate:
    """Test update_sourcecommit_manifest function."""

    @pytest.mark.asyncio
    async def test_partial_update_preserves_structure(self):
        """Test that YAML partial update preserves existing manifest structure."""
        existing_manifest = """apiVersion: apps/v1
kind: Deployment
metadata:
  name: test-app
  labels:
    app: test-app
    version: v1
spec:
  replicas: 3
  selector:
    matchLabels:
      app: test-app
  template:
    metadata:
      labels:
        app: test-app
    spec:
      containers:
      - name: test-app
        image: old-registry.com/old-image:v1
        ports:
        - containerPort: 8080
        env:
        - name: CUSTOM_VAR
          value: "custom-value"
        resources:
          requests:
            memory: "256Mi"
            cpu: "200m"
"""

        with patch("app.services.ncp_pipeline._call_ncp_rest_api") as mock_api:
            # Mock project ID fetch
            mock_api.side_effect = [
                {"result": {"projectId": "test-project-123"}},
                {
                    "result": {
                        "blobId": "abc123",
                        "content": __import__("base64").b64encode(existing_manifest.encode()).decode()
                    }
                },
                {"result": {"id": "commit-456"}}
            ]

            result = await update_sourcecommit_manifest(
                repo_name="test-repo",
                image_url="new-registry.com/new-image:v2",
                branch="main",
                manifest_path="k8s/deployment.yaml"
            )

            # Verify commit was made
            assert result["status"] == "updated"
            assert result["image"] == "new-registry.com/new-image:v2"
            assert result["commit"]["id"] == "commit-456"

            # Verify the YAML update preserved structure
            commit_call = mock_api.call_args_list[2]
            import base64
            committed_content = base64.b64decode(
                commit_call[0][2]["actions"][0]["content"]
            ).decode()

            import yaml
            manifest = yaml.safe_load(committed_content)

            # Image should be updated
            assert manifest["spec"]["template"]["spec"]["containers"][0]["image"] == "new-registry.com/new-image:v2"

            # Other fields should be preserved
            assert manifest["metadata"]["labels"]["version"] == "v1"
            assert manifest["spec"]["replicas"] == 3
            assert manifest["spec"]["template"]["spec"]["containers"][0]["env"][0]["name"] == "CUSTOM_VAR"
            assert manifest["spec"]["template"]["spec"]["containers"][0]["resources"]["requests"]["memory"] == "256Mi"

    @pytest.mark.asyncio
    async def test_creates_default_when_file_not_exists(self):
        """Test that default manifest is created when file doesn't exist."""
        with patch("app.services.ncp_pipeline._call_ncp_rest_api") as mock_api:
            # Mock project ID fetch and file not found (404)
            mock_api.side_effect = [
                {"result": {"projectId": "test-project-123"}},
                HTTPException(status_code=404, detail="File not found"),
                {"result": {"id": "commit-789"}}
            ]

            result = await update_sourcecommit_manifest(
                repo_name="new-repo",
                image_url="registry.com/app:latest",
                app_name="my_app",
                port=3000
            )

            # Verify commit was made with default manifest
            assert result["status"] == "updated"

            commit_call = mock_api.call_args_list[2]
            import base64
            committed_content = base64.b64decode(
                commit_call[0][2]["actions"][0]["content"]
            ).decode()

            # Verify default manifest structure
            assert "kind: Deployment" in committed_content
            assert "image: registry.com/app:latest" in committed_content
            assert "name: my_app" in committed_content
            assert "containerPort: 3000" in committed_content

    @pytest.mark.asyncio
    async def test_handles_invalid_yaml(self):
        """Test that invalid YAML triggers default manifest generation."""
        invalid_yaml = "this is not: valid: yaml: content"

        with patch("app.services.ncp_pipeline._call_ncp_rest_api") as mock_api:
            mock_api.side_effect = [
                {"result": {"projectId": "test-project-123"}},
                {
                    "result": {
                        "blobId": "corrupt123",
                        "content": __import__("base64").b64encode(invalid_yaml.encode()).decode()
                    }
                },
                {"result": {"id": "commit-recover"}}
            ]

            result = await update_sourcecommit_manifest(
                repo_name="corrupt-repo",
                image_url="registry.com/fixed:v1"
            )

            # Should succeed by generating default manifest
            assert result["status"] == "updated"
            assert result["commit"]["id"] == "commit-recover"

    @pytest.mark.asyncio
    async def test_raises_when_project_not_found(self):
        """Test that HTTPException is raised when project ID cannot be found."""
        with patch("app.services.ncp_pipeline._call_ncp_rest_api") as mock_api:
            mock_api.return_value = {"result": {}}  # No projectId

            with pytest.raises(HTTPException) as exc_info:
                await update_sourcecommit_manifest(
                    repo_name="missing-project-repo",
                    image_url="registry.com/app:v1"
                )

            assert exc_info.value.status_code == 404
            assert "Project ID not found" in str(exc_info.value.detail)


class TestImageVerification:
    """Test _verify_ncr_manifest_exists function."""

    @pytest.mark.asyncio
    async def test_verifies_existing_image(self):
        """Test successful image verification."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200

            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)

            result = await _verify_ncr_manifest_exists("registry.com/app:v1")

            assert result["exists"] is True
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_handles_authentication(self):
        """Test image verification with authentication flow."""
        with patch("httpx.AsyncClient") as mock_client, \
             patch("app.services.ncp_pipeline.settings") as mock_settings:

            mock_settings.ncp_access_key = "test-key"
            mock_settings.ncp_secret_key = "test-secret"

            # First response: 401 with WWW-Authenticate
            mock_401 = MagicMock()
            mock_401.status_code = 401
            mock_401.headers = {
                "WWW-Authenticate": 'Bearer realm="https://auth.registry.com/token",service="registry",scope="repository:app:pull"'
            }

            # Token response
            mock_token = MagicMock()
            mock_token.status_code = 200
            mock_token.text = '{"token": "auth-token-123"}'
            mock_token.json.return_value = {"token": "auth-token-123"}

            # Authenticated response
            mock_200 = MagicMock()
            mock_200.status_code = 200

            mock_get = AsyncMock(side_effect=[mock_401, mock_token, mock_200])
            mock_client.return_value.__aenter__.return_value.get = mock_get

            result = await _verify_ncr_manifest_exists("registry.com/app:v1")

            assert result["exists"] is True
            assert result["code"] == 200

    @pytest.mark.asyncio
    async def test_handles_missing_image(self):
        """Test verification when image doesn't exist."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 404

            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)

            result = await _verify_ncr_manifest_exists("registry.com/missing:v1")

            assert result["exists"] is False
            assert result["code"] == 404


class TestDefaultManifestGeneration:
    """Test _generate_default_manifest function."""

    def test_generates_valid_yaml(self):
        """Test that generated manifest is valid YAML."""
        manifest = _generate_default_manifest(
            app_name="test_app",
            image_url="registry.com/test:v1",
            port=8080
        )

        import yaml
        parsed = yaml.safe_load(manifest)

        assert parsed["apiVersion"] == "apps/v1"
        assert parsed["kind"] == "Deployment"
        assert parsed["metadata"]["name"] == "test_app"
        assert parsed["spec"]["template"]["spec"]["containers"][0]["image"] == "registry.com/test:v1"
        assert parsed["spec"]["template"]["spec"]["containers"][0]["ports"][0]["containerPort"] == 8080

    def test_includes_resource_limits(self):
        """Test that default manifest includes resource limits."""
        manifest = _generate_default_manifest(
            app_name="resource_app",
            image_url="registry.com/app:v1",
            port=3000
        )

        import yaml
        parsed = yaml.safe_load(manifest)

        resources = parsed["spec"]["template"]["spec"]["containers"][0]["resources"]
        assert resources["requests"]["memory"] == "128Mi"
        assert resources["requests"]["cpu"] == "100m"
        assert resources["limits"]["memory"] == "256Mi"
        assert resources["limits"]["cpu"] == "200m"
