# Skills — cdk_infra_test

## Ao trabalhar com stacks CDK

- Cada recurso AWS deve ter seu próprio Construct
- Sempre use `RemovalPolicy.RETAIN` para RDS e S3 em produção
- Nunca hardcode ARNs — use `Stack.of(self).account` e `.region`
- Nomes de recursos devem incluir o ambiente: `{name}-{env}`
- Sempre exporte outputs importantes com `CfnOutput`

## Ao modificar a FastAPI

- Todas as funções devem ter type hints
- Use `async def` para endpoints que fazem I/O com banco
- Sempre adicione `/health` em novos módulos
- Erros devem retornar `HTTPException` com código e mensagem clara

## Ao trabalhar com Puppet

- Módulos novos ficam em `puppet/modules/{nome}/`
- Manifests devem ser idempotentes (podem rodar N vezes)
- Sempre teste localmente antes de subir para o S3

## Ao fazer deploy

1. Rode `cdk synth` primeiro e revise o diff
2. Rode os testes: `pytest tests/`
3. Só então execute `cdk deploy`
4. Confirme que os outputs do CloudFormation batem com o esperado

## Segurança — regras obrigatórias

- Nenhuma credencial em código ou variável de ambiente em texto plano
- Toda senha/token vai para o Secrets Manager
- Security Groups devem ter o menor escopo possível
- Sem `0.0.0.0/0` em inbound de recursos privados

## Sempre que houver atualizações em qualquer código

- O README.md deve ser atualizado com as novas modificações
- O README-EN.md também deve receber as atualizações de conteúdo
