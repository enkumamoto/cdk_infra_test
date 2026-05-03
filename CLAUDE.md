# cdk_infra_test

## Visão geral

Infraestrutura AWS provisionada com CDK (Python). Inclui VPC,
ECS Fargate, RDS Aurora PostgreSQL, ALB, Client VPN e Bastion
Host configurado via Puppet.

## Stack de tecnologias

- **IaC**: AWS CDK v2 (Python)
- **App**: FastAPI (Python)
- **Container**: ECS Fargate + ECR
- **Banco**: Aurora PostgreSQL Serverless v2
- **Config**: Puppet (Bastion Host)
- **CI/CD**: GitHub Actions

## Estrutura do projeto

cdk_infra_test/ # Stacks CDK (VPC, ECS, RDS, ALB, VPN)
app_fastapi/ # Aplicação FastAPI
puppet/ # Manifests Puppet
tests/ # Testes CDK
.github/ # Pipeline CI/CD

## Comandos principais

# Instalar dependências

pip install -r requirements.txt

# Verificar síntese do CDK

cdk synth

# Deploy da infraestrutura

cdk deploy

# Bootstrap (primeira vez)

cdk bootstrap

## Convenções

- Stacks CDK em snake_case
- Uma stack por serviço AWS
- Secrets via AWS Secrets Manager (nunca em código)
- Variáveis de ambiente: DB_NAME, DB_HOST

## Fluxo de desenvolvimento

1. Modificar stack em cdk_infra_test/
2. Rodar cdk synth para validar
3. Push na main dispara GitHub Actions
4. GitHub Actions faz cdk deploy automaticamente
