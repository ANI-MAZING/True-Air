#!/usr/bin/env bash
# Build, push to ECR and deploy the CloudFormation stack.
# Usage: AWS_REGION=ap-south-1 ./scripts/deploy.sh [alert-email]
set -euo pipefail
cd "$(dirname "$0")/.."

REGION="${AWS_REGION:-ap-south-1}"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
REPO=trueair
TAG="$(date +%Y%m%d%H%M%S)"
IMAGE="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/$REPO:$TAG"

aws ecr describe-repositories --repository-names "$REPO" --region "$REGION" >/dev/null 2>&1 \
  || aws ecr create-repository --repository-name "$REPO" --region "$REGION" >/dev/null
aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"

docker build --platform linux/amd64 -t "$IMAGE" .
docker push "$IMAGE"

aws cloudformation deploy --region "$REGION" --stack-name trueair \
  --template-file infra/template.yaml --capabilities CAPABILITY_IAM \
  --parameter-overrides ImageUri="$IMAGE" AlertEmail="${1:-}"

aws cloudformation describe-stacks --region "$REGION" --stack-name trueair \
  --query "Stacks[0].Outputs" --output table
