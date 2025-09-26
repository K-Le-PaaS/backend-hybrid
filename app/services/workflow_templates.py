from ..core.config import get_settings


def get_ci_template() -> str:
    s = get_settings()
    branch = s.github_branch_main or "main"
    template = """
name: Service CI/CD (buildpacks)

on:
  push:
    branches: [ "__BRANCH__" ]
    paths: [ "**" ]
  workflow_dispatch:

permissions:
  contents: read

jobs:
  buildpack-build:
    runs-on: ubuntu-latest
    env:
      BUILD_PATH: .
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Install pack (Buildpacks CLI)
        uses: buildpacks/github-actions/setup-pack@v5.8.1

      - name: Login to Docker Hub
        uses: docker/login-action@v3
        with:
          registry: docker.io
          username: ${{ secrets.DOCKER_ID }}
          password: ${{ secrets.DOCKER_PASSWD }}

      - name: Set SERVICE_NAME / NAMESPACE / IMAGE_REPO
        run: |
          SERVICE_NAME="${GITHUB_REPOSITORY##*/}"
          NAMESPACE="${{ secrets.DOCKER_NAMESPACE || secrets.DOCKER_ID }}"
          echo "SERVICE_NAME=${SERVICE_NAME}" >> "$GITHUB_ENV"
          echo "NAMESPACE=${NAMESPACE}" >> "$GITHUB_ENV"
          echo "IMAGE_REPO=docker.io/${NAMESPACE}/${SERVICE_NAME}" >> "$GITHUB_ENV"

      - name: Ensure jq is installed
        run: |
          sudo apt-get update -y
          sudo apt-get install -y jq

      - name: Ensure Docker Hub repository exists
        env:
          NAMESPACE: ${{ env.NAMESPACE }}
          REPO: ${{ env.SERVICE_NAME }}
          DH_USER: ${{ secrets.DOCKER_ID }}
          DH_PASS: ${{ secrets.DOCKERHUB_PAT || secrets.DOCKER_PASSWD }}
        run: |
          set -e
          base="https://hub.docker.com/v2"
          TOKEN=$(curl -s -X POST -H "Content-Type: application/json" \
            -d "{\"username\":\"$DH_USER\",\"password\":\"$DH_PASS\"}" \
            "$base/users/login" | jq -r '.token')
          if [ -z "$TOKEN" ] || [ "$TOKEN" = "null" ]; then
            echo "Failed to obtain Docker Hub token"; exit 1
          fi
          status=$(curl -s -o /dev/null -w "%{http_code}" \
            -H "Authorization: JWT $TOKEN" \
            "$base/repositories/$NAMESPACE/$REPO/")
          if [ "$status" = "200" ]; then
            echo "Repository exists: $NAMESPACE/$REPO"; exit 0
          fi
          if [ "$status" != "404" ]; then
            echo "Unexpected status: $status"; exit 1
          fi
          create_url="$base/repositories/"
          payload=$(jq -n --arg ns "$NAMESPACE" --arg name "$REPO" --argjson private false '{namespace:$ns, name:$name, is_private:$private}')
          create_status=$(curl -s -o /tmp/dh_create_resp.json -w "%{http_code}" \
            -H "Authorization: JWT $TOKEN" -H "Content-Type: application/json" \
            -d "$payload" "$create_url")
          if [ "$create_status" != "201" ] && [ "$create_status" != "200" ]; then
            echo "Create failed: HTTP $create_status"; cat /tmp/dh_create_resp.json || true; exit 1
          fi
          echo "Created repository: $NAMESPACE/$REPO"

      - name: Compute tag
        id: vars
        run: |
          SHORT_SHA=${GITHUB_SHA::7}
          echo "tag=${SHORT_SHA}" >> "$GITHUB_OUTPUT"

      - name: Build & push with pack (sha + latest)
        run: |
          pack version
          pack build "${{ env.IMAGE_REPO }}:${{ steps.vars.outputs.tag }}" \
            --builder paketobuildpacks/builder-jammy-base \
            --path "${{ env.BUILD_PATH }}" \
            --publish \
            --tag "${{ env.IMAGE_REPO }}:latest"

      # Note: deployment-config 업데이트는 백엔드 웹훅이 처리합니다
"""
    return template.replace("__BRANCH__", branch).strip()


