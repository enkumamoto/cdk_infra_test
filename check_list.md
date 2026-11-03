# Checklist de correções: Teste Técnico DevOps

Use este arquivo como roteiro de estudo e correção. Cada item traz:

- **Status:** ✅ ok · ⚠️ parcial · ❌ não atende
- **Problema:** o que está errado hoje (com o arquivo)
- **Como fazer:** passos concretos
- **Por que fazer:** o conceito por trás (o que aprender)
- **Resultado esperado:** como verificar que ficou certo

Análise feita sobre o commit `b17f81f`. O teste unitário (`pytest`) foi executado e **falha** (ver item 1).

---

## Visão geral: requisitos do `Test.md`

| Requisito | Status | Itens |
|---|---|---|
| Código no GitHub/GitLab | ✅ | — |
| App rodando em containers Docker | ⚠️ | 4, 5 |
| Dockerfile **com script de entrypoint** | ❌ | 8 |
| Banco em recurso próprio e resiliente a updates da app | ✅ | — |
| CI/CD para infraestrutura | ❌ | 1, 3, 11 |
| CI/CD para deploy da aplicação | ⚠️ | 4, 6, 11 |
| Gerenciamento administrativo da app em execução | ⚠️ | 12 |
| Bastion **não** em rede pública | ✅ | — |
| Bastion **não** hospeda o banco | ✅ | — |
| Bastion usa Puppet para gerenciar usuários | ❌ | 2, 3, 9 |
| Bastion hospeda ferramenta de DB (pgAdmin/phpMyAdmin) | ❌ | 7 |
| Diagrama da infraestrutura | ⚠️ | 14 |
| Guia para desenvolvedores | ❌ | 15 |
| Guia para administradores | ❌ | 15 |

Ordem sugerida: os itens 1 a 5 são **bloqueadores**, porque hoje o deploy não funciona de ponta a ponta. Depois vêm os 6 a 10 (requisitos obrigatórios) e, por fim, os de 11 em diante (qualidade e documentação).

---

## 🔴 Bloqueadores (o deploy não funciona hoje)

### 1. `cdk synth` quebra: método inexistente no alarme do ALB

- **Status:** ❌
- **Problema:** em [cdk_infra_test/cdk_infra_test_stack.py:498](cdk_infra_test/cdk_infra_test_stack.py#L498), `listener.metric_target_response_time()` não existe em `ApplicationListener`. O `pytest` falha com `AttributeError`, e o `cdk synth` / `cdk deploy` do workflow de infra falham pelo mesmo motivo. Além disso, o alarme se chama `AlbUnhealthyHostsAlarm`, mas mede latência.
- **Como fazer:**
  1. Troque por `alb.metrics.target_response_time()` (ou `target_group.metrics.target_response_time()`, guardando o retorno de `listener.add_targets(...)`).
  2. Renomeie o construct para `AlbLatencyAlarm`. Se quiser um alarme de hosts não saudáveis, crie outro com `target_group.metrics.unhealthy_host_count()`.
  3. Troque `container_insights=True` (depreciado) por `container_insights_v2=ecs.ContainerInsights.ENABLED`.
- **Por que fazer:** a API do CDK muda entre versões, e `requirements.txt` usa `>=2.238.0`, então cada instalação pode trazer uma versão diferente. Rodar `pytest`/`cdk synth` no CI **antes** do deploy pega esse tipo de erro (ver item 11).
- **Resultado esperado:** `pytest` passa (foi verificado numa cópia com essa troca: `1 passed`) e `cdk synth` gera o template sem erro.

### 2. Caminho do Puppet no S3 diverge entre o workflow e o user data

- **Status:** ❌
- **Problema:** [.github/workflows/puppet-sync.yml](.github/workflows/puppet-sync.yml) faz `aws s3 sync puppet/ s3://$PUPPET_BUCKET`, o que grava os arquivos na **raiz** do bucket (`s3://bucket/manifests/site.pp`). O user data em [cdk_infra_test_stack.py:221](cdk_infra_test/cdk_infra_test_stack.py#L221) baixa de `s3://bucket/puppet`, um prefixo que nunca existe. Resultado: `/opt/puppet` fica vazio e `puppet apply` falha.
- **Como fazer:**
  1. Escolha **um** prefixo e use o mesmo nos dois lugares, por exemplo `aws s3 sync puppet/ s3://$PUPPET_BUCKET/puppet --delete`.
  2. Melhor ainda: publique o Puppet pelo próprio CDK com `aws_s3_deployment.BucketDeployment(sources=[Source.asset("puppet")], destination_key_prefix="puppet")`. Assim o bucket nunca está vazio quando o Bastion sobe pela primeira vez.
- **Por que fazer:** uma "fonte da verdade" para caminhos e nomes evita divergência silenciosa entre pipeline e infra. Com o `BucketDeployment` também some a **condição de corrida**: hoje o Bastion sobe antes de qualquer sync do Puppet.
- **Resultado esperado:** `aws s3 ls s3://<bucket>/puppet/manifests/` lista `site.pp`, e no Bastion `ls /opt/puppet/manifests` mostra o arquivo.

### 3. Bootstrap do Bastion: Puppet não instala, não acha os módulos e não reaplica

- **Status:** ❌
- **Problema** (user data em [cdk_infra_test_stack.py:215-223](cdk_infra_test/cdk_infra_test_stack.py#L215-L223)):
  1. `yum install -y puppet` não funciona no Amazon Linux 2023, que não tem o pacote `puppet` nos repositórios padrão.
  2. `puppet apply /opt/puppet/manifests/site.pp` roda sem `--modulepath`, então as classes `users` e `phpmyadmin` não são encontradas (`Could not find class users`).
  3. O user data roda **só no primeiro boot** (cloud-init). O "Reboot Bastion" do workflow não reaplica o Puppet, apenas derruba as sessões dos administradores.
- **Como fazer:**
  1. Instale o agente oficial, por exemplo:
     `rpm -Uvh https://yum.puppet.com/puppet8-release-el-9.noarch.rpm && dnf install -y puppet-agent`
     (o binário fica em `/opt/puppetlabs/bin/puppet`). Valide qual repositório é compatível com AL2023 ou use Rocky/Alma 9 como AMI do Bastion.
  2. Rode: `/opt/puppetlabs/bin/puppet apply --modulepath=/opt/puppet/modules /opt/puppet/manifests/site.pp`.
  3. Crie um script `/usr/local/bin/puppet-run.sh` (sync do S3 + apply) e chame-o:
     - no user data (primeiro boot);
     - no workflow, via **SSM Run Command** no lugar do reboot:
       `aws ssm send-command --instance-ids $ID --document-name AWS-RunShellScript --parameters 'commands=["/usr/local/bin/puppet-run.sh"]'`;
     - opcionalmente, num `systemd timer` ou `cron` a cada 30 min, para corrigir drift.
  4. Coloque `set -euxo pipefail` no início do user data para que falhas apareçam em `/var/log/cloud-init-output.log`.
- **Por que fazer:** gerência de configuração existe para **convergir o estado continuamente** e de forma idempotente. Rodar uma vez no boot não é gerência de configuração. O SSM Run Command aplica mudanças sem SSH e sem downtime.
- **Resultado esperado:** um push em `puppet/` dispara o workflow, o `send-command` termina com `Success` e `id adminuser` funciona no Bastion sem reboot.

### 4. Health check do container usa `curl`, que não existe na imagem

- **Status:** ❌
- **Problema:** em [cdk_infra_test_stack.py:393](cdk_infra_test/cdk_infra_test_stack.py#L393) o health check do ECS é `curl -f http://localhost:8000/health`, mas `python:3.11-slim` não tem `curl`. Toda task fica `UNHEALTHY`, o ECS a mata e o circuit breaker faz rollback. O `HEALTHCHECK` do [app_fastapi/Dockerfile](app_fastapi/Dockerfile) (que usa Python) é **ignorado** pelo ECS, que só usa o health check da task definition.
- **Como fazer:** use o mesmo comando do Dockerfile:
  `command=["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=3)\" || exit 1"]`
  (ou instale `curl` na imagem, o que aumenta a superfície de ataque).
- **Por que fazer:** o health check roda **dentro** do container, então só pode usar binários que existem nele. Imagens slim/distroless não trazem ferramentas de debug.
- **Resultado esperado:** no console do ECS a task aparece com `Health status: HEALTHY`, e `aws ecs describe-services` mostra `runningCount == desiredCount`.

### 5. Primeiro deploy: ECS sobe apontando para uma imagem que ainda não existe

- **Status:** ❌
- **Problema:** o stack cria o repositório ECR **e** um serviço ECS com `desired_count=2` usando `:latest` ([cdk_infra_test_stack.py:373](cdk_infra_test/cdk_infra_test_stack.py#L373)). Num deploy do zero o repositório está vazio, as tasks falham com `CannotPullContainerError`, o CloudFormation fica esperando a estabilização e acaba falhando ou fazendo rollback. O workflow da app, por sua vez, depende do stack já existir: é um ovo e galinha.
- **Como fazer** (escolha uma):
  - **A (mais simples):** `ecs.ContainerImage.from_asset("app_fastapi")`. O CDK faz o build e o push da imagem no `cdk deploy`.
  - **B (separa infra de app):** receba a tag da imagem como contexto/parâmetro (`cdk deploy -c imageTag=<sha>`). No bootstrap, use uma imagem pública placeholder ou `desired_count=0`.
  - **C:** separe em dois stacks (`NetworkDataStack` com VPC/RDS/ECR e `AppStack` com ECS/ALB) e rode, nesta ordem: deploy do primeiro, build/push da imagem, deploy do segundo.
- **Por que fazer:** a ordem de criação dos recursos precisa ser **reproduzível do zero** (um ambiente novo, ou recuperação de desastre). Se só funciona porque alguém fez push manual antes, não é automação.
- **Resultado esperado:** numa conta limpa, `cdk deploy` (ou o pipeline) sobe tudo de primeira e `curl http://<ALB>/health` retorna `200`.

---

## 🟠 Requisitos obrigatórios não atendidos

### 6. Deploy com a tag mutável `latest`: o rollback não volta a versão

- **Status:** ⚠️
- **Problema:** [.github/workflows/app-build-push.yml](.github/workflows/app-build-push.yml) faz push de `:<sha>` e `:latest` e chama `update-service --force-new-deployment`. A task definition continua apontando para `:latest`. Se a versão nova quebrar, o circuit breaker "volta" para a mesma task definition, que puxa o **mesmo `latest` quebrado**. O SHA é gerado, mas não é usado no deploy.
- **Como fazer:**
  1. No workflow, use `aws-actions/amazon-ecs-render-task-definition` + `aws-actions/amazon-ecs-deploy-task-definition` para registrar uma **nova revisão** da task definition com `image: <ecr>:<sha>`.
  2. Ou passe o SHA para o CDK (`cdk deploy -c imageTag=${{ github.sha }}`) e use `from_ecr_repository(repo, tag=image_tag)`.
  3. Configure o ECR com `image_tag_mutability=IMMUTABLE` e deixe de publicar `latest`.
- **Por que fazer:** um artefato imutável e versionado é a base de deploys reproduzíveis e de rollback confiável. Cada revisão da task definition passa a corresponder a uma versão exata do código.
- **Resultado esperado:** `aws ecs describe-task-definition` mostra a imagem com o SHA do commit. Um deploy propositalmente quebrado faz o ECS voltar para a revisão anterior, que continua funcionando.

### 7. phpMyAdmin não gerencia PostgreSQL: o Bastion precisa de pgAdmin

- **Status:** ❌
- **Problema:** o banco é **Aurora PostgreSQL**, mas [puppet/modules/phpmyadmin/manifests/init.pp](puppet/modules/phpmyadmin/manifests/init.pp) instala o phpMyAdmin, que só fala MySQL/MariaDB. Além disso, `phpmyadmin` e `php-mysqli` não existem nos repositórios do AL2023, então o `puppet apply` falha. Não há configuração de servidor nem de credenciais, e a SG do Bastion não permite acesso HTTP.
- **Como fazer:**
  1. Crie o módulo `puppet/modules/pgadmin/` e remova o `phpmyadmin`.
  2. Abordagem recomendada: o Puppet instala o Docker e roda o pgAdmin como container gerenciado por uma unidade systemd:
     - `package { 'docker': }` e `service { 'docker': ensure => running }`;
     - `file { '/etc/systemd/system/pgadmin.service': content => epp(...) }` rodando `docker run --rm -p 127.0.0.1:5050:80 -e PGADMIN_DEFAULT_EMAIL=... -e PGADMIN_DEFAULT_PASSWORD=... -v /opt/pgadmin/servers.json:/pgadmin4/servers.json dpage/pgadmin4:<versão fixa>`;
     - `file { '/opt/pgadmin/servers.json': }` já com o endpoint do Aurora pré-cadastrado.
  3. Não coloque a senha do pgAdmin no Git: leia do Secrets Manager/SSM Parameter Store no script de bootstrap (o Bastion já tem role IAM) ou use Hiera com `hiera-eyaml`.
  4. Acesso: **SSM port forwarding**, sem abrir portas na SG:
     `aws ssm start-session --target <bastion-id> --document-name AWS-StartPortForwardingSession --parameters '{"portNumber":["5050"],"localPortNumber":["5050"]}'` e depois abra `http://localhost:5050`.
- **Por que fazer:** a ferramenta tem que ser compatível com o banco. Rodar ferramentas não críticas como container isola as dependências e evita brigar com pacotes do SO. Fazer bind em `127.0.0.1` mais o túnel SSM mantém o Bastion fechado.
- **Resultado esperado:** com o túnel aberto, `http://localhost:5050` mostra o login do pgAdmin, o servidor Aurora já aparece cadastrado e a conexão funciona (a SG do RDS já libera 5432 a partir do Bastion).

### 8. Falta o script de entrypoint no Dockerfile

- **Status:** ❌
- **Problema:** o `Test.md` pede explicitamente "Dockerfiles (incluindo scripts de entrypoint)". O [app_fastapi/Dockerfile](app_fastapi/Dockerfile) só tem `CMD ["uvicorn", ...]`. Além disso, a criação de tabela fica no startup da app ([app_fastapi/main.py:43-60](app_fastapi/main.py#L43-L60)) e roda em **cada worker de cada task** ao mesmo tempo.
- **Como fazer:**
  1. Crie `app_fastapi/entrypoint.sh`:
     ```sh
     #!/bin/sh
     set -eu
     : "${DB_HOST:?}" "${DB_NAME:?}" "${DB_USER:?}" "${DB_PASSWORD:?}"
     # espera o banco responder (timeout)
     python -m app.wait_for_db
     # migrações (opcional: Alembic)
     [ "${RUN_MIGRATIONS:-true}" = "true" ] && alembic upgrade head
     exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers "${WEB_CONCURRENCY:-2}"
     ```
  2. No Dockerfile: `COPY entrypoint.sh /entrypoint.sh`, `RUN chmod +x /entrypoint.sh`, `ENTRYPOINT ["/entrypoint.sh"]`.
  3. Adote o Alembic para o schema, o que tira o `CREATE TABLE` do código da aplicação.
- **Por que fazer:** o entrypoint é o lugar de validar config, esperar dependências e rodar migrações **antes** de a app aceitar tráfego. O `exec` faz o uvicorn virar PID 1 e receber o `SIGTERM` do ECS, o que dá shutdown gracioso. Migrações versionadas são o que torna o banco realmente "resiliente a atualizações da aplicação".
- **Resultado esperado:** `docker run` sem `DB_HOST` falha imediatamente com uma mensagem clara. Com o banco disponível, o log mostra a migração aplicada e depois o uvicorn subindo.

### 9. Puppet não gerencia credenciais de administradores

- **Status:** ❌
- **Problema:** [puppet/modules/users/manifests/init.pp](puppet/modules/users/manifests/init.pp) cria só o `adminuser` e uma pasta `.ssh` vazia. Não há chave pública (`authorized_keys`), sudo, grupo administrativo, nem forma de adicionar ou remover administradores. O requisito é "Credenciais de usuários administrativos". A instância também não tem key pair, então hoje ninguém consegue fazer SSH.
- **Como fazer:**
  1. Transforme a lista de admins em **dados** (Hiera ou parâmetro):
     ```puppet
     # puppet/data/common.yaml
     users::admins:
       alice: { ssh_key: 'AAAAC3...', ensure: present }
       bob:   { ssh_key: 'AAAAC3...', ensure: absent }
     ```
  2. No módulo, itere: `user` (com `groups => ['wheel']`, `purge_ssh_keys => true`), `ssh_authorized_key`, e `file { '/etc/sudoers.d/admins': content => '%wheel ALL=(ALL) NOPASSWD: ALL', mode => '0440', validate_cmd => '/usr/sbin/visudo -cf %' }`.
  3. Endureça o `sshd` (`PasswordAuthentication no`, `PermitRootLogin no`) com `file_line` ou template e um `notify => Service['sshd']`.
  4. Inclua `hiera.yaml` e use `--hiera_config` no `puppet apply`.
- **Por que fazer:** separar **código** (como criar usuário) de **dados** (quem é admin) é a ideia central do Puppet/Hiera. Fazer onboarding ou offboarding vira um PR revisável, e `ensure => absent` remove o acesso de forma auditável.
- **Resultado esperado:** um PR que adiciona um admin no YAML, depois do merge e do workflow, permite `ssh alice@<bastion>` via VPN e `sudo -l` funciona. Removendo o admin, o acesso cai.

### 10. VPN: certificados ACM públicos para domínio `.local` nunca validam

- **Status:** ❌
- **Problema:** em [cdk_infra_test_stack.py:62-72](cdk_infra_test/cdk_infra_test_stack.py#L62-L72), `acm.Certificate(domain_name="vpn-server.devopstest.local")` solicita um certificado **público** (a validação padrão é por e-mail). Domínios `.local` não podem ser validados, então o CloudFormation fica preso em `CREATE_IN_PROGRESS` até dar timeout. A Private CA criada nas linhas 27-60 nunca é usada para emitir esses certificados. Além disso, o usuário final precisa de um certificado de **cliente** com chave privada exportável para montar o `.ovpn`, e isso não está previsto.
- **Como fazer:**
  - **A (barata e didática, recomendada para teste):** gere CA, server e client com `easy-rsa` (script em `scripts/vpn-certs.sh`), importe com `aws acm import-certificate` e passe os ARNs para o CDK via contexto. Remova a `CfnCertificateAuthority`.
  - **B (Private CA):** use `acm.PrivateCertificate(certificate_authority=acmpca.CertificateAuthority.from_certificate_authority_arn(...))` para o servidor e emita os certificados de cliente com `aws acm-pca issue-certificate`. Atenção: a Private CA custa cerca de US$ 400/mês.
  - **Alternativa:** remova a VPN e use apenas **SSM Session Manager** e port forwarding. O Bastion continua privado e o custo cai bastante (a VPN cobra por associação e por hora de conexão).
- **Por que fazer:** a autenticação mútua TLS exige que server e client confiem na mesma CA. Uma CA pública não emite certificado para nomes internos. Entender a cadeia de confiança (CA → server/client) é essencial para depurar VPN, mTLS e service mesh.
- **Resultado esperado:** o stack conclui o deploy, `aws ec2 export-client-vpn-client-configuration` gera o `.ovpn` e, com o cert/key do cliente, a conexão funciona e `ping <ip-privado-do-bastion>` responde.

---

## 🟡 Qualidade, segurança e operação

### 11. Pipelines sem teste, sem gate e sem ordem entre si

- **Status:** ⚠️
- **Problema:**
  - [.github/workflows/infra-deploy.yml](.github/workflows/infra-deploy.yml) faz `cdk deploy --require-approval never` direto no push para `main`, sem rodar `pytest` nem `cdk diff`. Foi assim que o erro do item 1 passou.
  - Não existe workflow de PR, nem lint ou teste para `app_fastapi/` (não há nenhum teste da aplicação).
  - A role OIDC (`secrets.AWS_ROLE`) não está em código nem documentada.
  - Os três workflows rodam de forma independente: um push que mexe em infra e app ao mesmo tempo pode fazer o deploy da app antes da infra.
- **Como fazer:**
  1. Crie `ci.yml` com `on: pull_request`: `pytest` (infra), `cdk synth`, `ruff`/`pytest` na app e `docker build` (sem push).
  2. No deploy de infra, rode `pytest` → `cdk diff` → `cdk deploy`, usando um `environment: production` com *required reviewers* no GitHub para ter aprovação manual.
  3. Fixe as versões: `aws-cdk-lib==X.Y.Z` em `requirements.txt` e `npm install -g aws-cdk@X.Y.Z`.
  4. Crie o OIDC provider e a role em código (um stack `GithubOidcStack`, ou documente os passos no guia de admin).
  5. Encadeie com `workflow_run` ou junte tudo num único workflow com `needs:` (infra → app).
- **Por que fazer:** CI (validar no PR) e CD (entregar o que já foi validado) são etapas diferentes. Deploy sem gate em `main` transforma qualquer erro de digitação em incidente. Versões fixas tornam o build reproduzível.
- **Resultado esperado:** um PR com erro de sintaxe no stack fica **vermelho** e não pode ser mergeado. O deploy de infra mostra o `diff` e espera aprovação.

### 12. Gerenciamento administrativo da aplicação em execução

- **Status:** ⚠️
- **Problema:** não há forma documentada nem habilitada de administrar a app rodando: sem ECS Exec, sem permissões no Bastion para ver logs ou serviços, e os alarmes do CloudWatch não têm ação (nenhum SNS), então ninguém é avisado.
- **Como fazer:**
  1. `ecs.FargateService(..., enable_execute_command=True)` e permissões `ssmmessages:*` na task role, o que permite `aws ecs execute-command --interactive --command /bin/sh`.
  2. Crie um `sns.Topic` com assinatura de e-mail e use `alarm.add_alarm_action(cw_actions.SnsAction(topic))` em todos os alarmes.
  3. Opcional: crie um `cloudwatch.Dashboard` com CPU, memória, 5xx do ALB, latência e conexões do RDS.
  4. Documente no guia de admin: escalar (`update-service --desired-count`), ver logs (`aws logs tail /aws/ecs/... --follow`), fazer rollback (`update-service --task-definition <revisão anterior>`) e rotacionar a senha do DB.
- **Por que fazer:** observabilidade sem alerta não é monitoramento. Acesso administrativo auditável (ECS Exec e SSM ficam registrados no CloudTrail) substitui SSH em containers.
- **Resultado esperado:** `aws ecs execute-command` abre um shell na task, e forçar um alarme (`aws cloudwatch set-alarm-state`) gera um e-mail.

### 13. Health check depende do banco (liveness × readiness) e outros detalhes da app

- **Status:** ⚠️
- **Problema:**
  - `/health` ([app_fastapi/main.py:93-111](app_fastapi/main.py#L93-L111)) consulta o banco, e o ECS e o ALB usam esse endpoint. Se o Aurora ficar indisponível ou fizer failover por alguns segundos, **todas** as tasks são marcadas unhealthy e recicladas, e a app nunca volta enquanto o banco não volta.
  - Se `get_pool()` falhar (banco fora no startup), `/health` responde 500 em vez de 503.
  - `task_role` recebe `logs:*` sem necessidade ([cdk_infra_test_stack.py:353-358](cdk_infra_test/cdk_infra_test_stack.py#L353-L358)): quem escreve os logs do driver `awslogs` é a execution role.
  - O ALB só escuta em HTTP:80, sem TLS.
  - `deletion_protection=True` no ALB e no RDS impede `cdk destroy` em ambiente de teste.
- **Como fazer:**
  1. Separe `/health/live` (só responde 200, usado pelo ECS) de `/health/ready` (consulta o banco, usado pelo ALB ou por monitoramento).
  2. Coloque o `get_pool()` dentro do `try` do health.
  3. Remova a policy de logs da task role.
  4. Se houver domínio, adicione um listener 443 com certificado ACM e redirecione 80 para 443.
  5. Torne a proteção configurável por ambiente (`-c env=dev|prod`).
- **Por que fazer:** *liveness* responde "o processo está vivo?" (se não, reinicie) e *readiness* responde "posso receber tráfego?" (se não, tire do balanceador). Misturar os dois causa reinícios em cascata por causa de uma dependência externa. Menor privilégio vale também para o que é "inofensivo".
- **Resultado esperado:** parar o banco (ou bloquear a SG) faz o ALB retornar 503, mas as tasks **não** são reiniciadas em loop. Ao restaurar o banco, o tráfego volta sozinho.

### 14. Diagrama não bate com o código

- **Status:** ⚠️
- **Problema:** o diagrama Mermaid do [README.md](README.md) existe, mas tem divergências: mostra `VPN → RDS` (a SG do RDS só libera Bastion e ECS); a tabela de alarmes diz "3 de 3" (o código usa `datapoints_to_alarm=2`); o fluxo de boot do Bastion mostra "Testa conectividade" com o RDS, coisa que nada faz; o README cita phpMyAdmin e reboot como se funcionassem.
- **Como fazer:** depois das correções, refaça o diagrama a partir do código. Inclua as SGs e portas nas setas (ex.: `ALB -->|8000| ECS`, `Bastion -->|5432| RDS`), o caminho do SSM e o fluxo de CI/CD. Opcionalmente, exporte um PNG (draw.io ou `cdk-dia`) em `docs/architecture.png`.
- **Por que fazer:** um diagrama errado é pior que nenhum, porque induz quem opera a erro durante um incidente. O diagrama deve refletir as regras de rede reais.
- **Resultado esperado:** cada seta do diagrama corresponde a uma regra de SG ou rota no stack, e vice-versa.

### 15. Faltam os guias de uso (desenvolvedor e administrador)

- **Status:** ❌
- **Problema:** o README descreve os recursos (o "o quê"), mas o `Test.md` pede **guias** (o "como") para dois públicos. Não há instruções de desenvolvimento local, nem de como conectar na VPN, acessar o Bastion e o pgAdmin, ou adicionar um admin.
- **Como fazer:**
  1. `docs/GUIA_DESENVOLVEDOR.md`:
     - rodar localmente com um `docker-compose.yml` (app + postgres);
     - criar migração (Alembic);
     - abrir PR, o que o CI valida e como acompanhar o deploy;
     - fazer rollback de uma versão;
     - ver logs da app.
  2. `docs/GUIA_ADMINISTRADOR.md`:
     - pré-requisitos (AWS CLI, plugin do Session Manager, cliente VPN);
     - obter o `.ovpn` e o certificado;
     - acessar o Bastion (SSM e SSH);
     - abrir o pgAdmin via túnel;
     - adicionar ou remover um admin via Puppet (PR no YAML);
     - rotacionar a senha do banco;
     - escalar o ECS e responder a alarmes;
     - primeiro deploy numa conta nova (bootstrap, role OIDC, secrets do GitHub).
  3. Linke os dois no topo do README.
- **Por que fazer:** um entregável operável é aquele que **outra pessoa** consegue usar sem perguntar a você. Escrever o guia também revela os passos manuais que deveriam ser automatizados.
- **Resultado esperado:** alguém sem contexto, seguindo só o guia, consegue subir a app localmente (dev) ou abrir o pgAdmin conectado ao Aurora (admin).

### 16. Pequenos ajustes

- **Status:** ⚠️
- **Problema / Como fazer:**
  - `source.bat` é sobra do template do CDK e pode ser removido.
  - `.gitignore` ignora `CLAUDE.md`/`SKILLS.md`, mas o histórico tem um commit que os adiciona. Decida se versiona ou não.
  - A versão `VER_14_6` do Aurora PostgreSQL é antiga. Prefira uma versão suportada mais recente (15/16).
  - A região `us-east-1` está fixa nos workflows e `app.py` não define `env`. Centralize num `vars.AWS_REGION` do GitHub e em `env=cdk.Environment(...)`.
  - Custo: 2 NAT Gateways + Client VPN + Private CA + Aurora com reader somam um valor alto para um teste. Documente isso ou parametrize (ex.: `nat_gateways=1` em dev, sem reader em dev).
  - O user data do Bastion não precisa de `yum install amazon-ssm-agent`, porque o agente já vem no AL2023.
- **Por que fazer:** higiene de repositório e consciência de custo também são avaliadas num teste de DevOps.
- **Resultado esperado:** um repositório sem arquivos órfãos e um README com uma seção "Custos estimados".

---

## Como validar tudo no final

1. `pytest` e `cdk synth` passam localmente e no CI do PR.
2. Numa conta/região limpa, um único fluxo (pipeline ou script documentado) sobe tudo do zero.
3. `curl http://<ALB>/health/ready` retorna `200`; `POST /items` e `GET /items` funcionam.
4. Um push em `app_fastapi/` gera uma nova revisão da task definition com o SHA, e uma versão quebrada faz rollback para a anterior.
5. Um push em `puppet/` aplica a mudança no Bastion sem reboot.
6. Pela VPN ou pelo SSM: SSH com um usuário criado pelo Puppet e pgAdmin acessível via túnel, conectado ao Aurora.
7. O Bastion não tem IP público (`aws ec2 describe-instances ... PublicIpAddress` vazio) e não roda nenhum banco.
8. Os guias de dev e de admin, seguidos por outra pessoa, funcionam sem ajuda.
