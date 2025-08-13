#!/bin/bash

# AWS Infrastructure Setup Script for RAG Knowledge Management System
# This script creates the necessary AWS resources for ECS Fargate deployment

set -e

# Configuration
AWS_REGION="us-east-1"
CLUSTER_NAME="rag-knowledge-cluster"
SERVICE_NAME="rag-knowledge-service"
ECR_REPOSITORY="rag-knowledge-system"
LOG_GROUP="/ecs/rag-knowledge-system"

echo "🚀 Setting up AWS infrastructure for RAG Knowledge Management System..."

# Create ECR Repository
echo "📦 Creating ECR repository..."
aws ecr create-repository \
    --repository-name $ECR_REPOSITORY \
    --region $AWS_REGION \
    --image-scanning-configuration scanOnPush=true \
    --encryption-configuration encryptionType=AES256 || echo "Repository might already exist"

# Create CloudWatch Log Group
echo "📊 Creating CloudWatch log group..."
aws logs create-log-group \
    --log-group-name $LOG_GROUP \
    --region $AWS_REGION || echo "Log group might already exist"

# Create ECS Cluster
echo "🏗️ Creating ECS cluster..."
aws ecs create-cluster \
    --cluster-name $CLUSTER_NAME \
    --capacity-providers FARGATE \
    --default-capacity-provider-strategy capacityProvider=FARGATE,weight=1 \
    --region $AWS_REGION || echo "Cluster might already exist"

# Create IAM roles (you'll need to run these with appropriate permissions)
echo "🔐 Creating IAM roles..."

# ECS Task Execution Role
cat > trust-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "ecs-tasks.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

aws iam create-role \
    --role-name ecsTaskExecutionRole \
    --assume-role-policy-document file://trust-policy.json || echo "Role might already exist"

aws iam attach-role-policy \
    --role-name ecsTaskExecutionRole \
    --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy

# ECS Task Role
aws iam create-role \
    --role-name ecsTaskRole \
    --assume-role-policy-document file://trust-policy.json || echo "Role might already exist"

# Create custom policy for task role
cat > task-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue",
        "s3:GetObject",
        "s3:PutObject"
      ],
      "Resource": "*"
    }
  ]
}
EOF

aws iam create-policy \
    --policy-name RAGTaskPolicy \
    --policy-document file://task-policy.json || echo "Policy might already exist"

aws iam attach-role-policy \
    --role-name ecsTaskRole \
    --policy-arn arn:aws:iam::$(aws sts get-caller-identity --query Account --output text):policy/RAGTaskPolicy

# Clean up temporary files
rm -f trust-policy.json task-policy.json

echo "✅ AWS infrastructure setup complete!"
echo ""
echo "📋 Next steps:"
echo "1. Update .aws/task-definition.json with your AWS Account ID"
echo "2. Set up GitHub Secrets:"
echo "   - AWS_ACCESS_KEY_ID"
echo "   - AWS_SECRET_ACCESS_KEY"
echo "3. Push your code to trigger the deployment pipeline"
echo ""
echo "🔗 ECR Repository URI: $(aws sts get-caller-identity --query Account --output text).dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPOSITORY"
