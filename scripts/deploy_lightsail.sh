#!/usr/bin/env bash
# Deploy TrueAir to an Amazon Lightsail container service.
# Used because the hackathon account's org policy blocks App Runner/ECS/ECR/CloudFormation.
# Usage: AWS_PROFILE=trueair ./scripts/deploy_lightsail.sh
# Needs: AWS CLI, Docker, lightsailctl (brew install aws/tap/lightsailctl)
set -euo pipefail
cd "$(dirname "$0")/.."

REGION="${AWS_REGION:-us-east-1}"
SERVICE="${SERVICE:-trueair}"
POWER="${POWER:-small}"     # nano | micro | small | medium ...
LS="aws lightsail --region $REGION"

if ! $LS get-container-services --service-name "$SERVICE" >/dev/null 2>&1; then
  echo "Creating container service $SERVICE ($POWER)..."
  $LS create-container-service --service-name "$SERVICE" --power "$POWER" --scale 1 >/dev/null
fi

echo "Waiting for service to be ready..."
until state=$($LS get-container-services --service-name "$SERVICE" --query 'containerServices[0].state' --output text) \
      && [[ "$state" == "READY" || "$state" == "RUNNING" ]]; do
  echo "  state: $state"; sleep 15
done

docker build --platform linux/amd64 -t trueair:latest .
IMAGE=$($LS push-container-image --service-name "$SERVICE" --label app --image trueair:latest \
        | grep -o ':[^ ]*\.app\.[0-9]*' | tail -1)
echo "Pushed $IMAGE"

cat > /tmp/trueair-containers.json <<JSON
{"app": {"image": "$IMAGE", "ports": {"8080": "HTTP"},
         "environment": {"TRUEAIR_TICK_SECONDS": "2"}}}
JSON
cat > /tmp/trueair-endpoint.json <<JSON
{"containerName": "app", "containerPort": 8080,
 "healthCheck": {"path": "/api/health", "intervalSeconds": 10, "timeoutSeconds": 5,
                 "healthyThreshold": 2, "unhealthyThreshold": 5, "successCodes": "200"}}
JSON

$LS create-container-service-deployment --service-name "$SERVICE" \
  --containers file:///tmp/trueair-containers.json \
  --public-endpoint file:///tmp/trueair-endpoint.json >/dev/null

echo "Deploying..."
until state=$($LS get-container-services --service-name "$SERVICE" --query 'containerServices[0].state' --output text) \
      && [[ "$state" == "RUNNING" ]]; do
  echo "  state: $state"; sleep 15
done
$LS get-container-services --service-name "$SERVICE" --query 'containerServices[0].url' --output text
