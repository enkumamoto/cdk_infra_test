# Teste Técnico de DevOps

## Objetivo

Implantar uma stack genérica de aplicação web de sua escolha em um provedor de nuvem. A solução deve ser automatizada para fornecer uma infraestrutura mínima funcional, incluindo:

- Deploy automatizado para alterações/atualizações da aplicação.
- Gerenciamento administrativo da aplicação em execução.

Espera-se que um **bastion host** seja utilizado para acessar os recursos da aplicação sem interferir na execução da mesma. As configurações desse host devem ser gerenciadas usando **Puppet**, configurando pelo menos:

- Credenciais de usuários administrativos.
- Uma ferramenta de gerenciamento de banco de dados (ex.: pgAdmin ou phpMyAdmin).

## Regras e Restrições

- **Controle de Código-Fonte:** A base de código deve estar hospedada no GitHub ou GitLab.
- **Banco de Dados:** Deve rodar em seu próprio recurso de nuvem e ser resiliente a atualizações da aplicação.
- **Execução:** A aplicação deve rodar utilizando containers Docker.
- **Automação:** Tanto a infraestrutura quanto o deploy da aplicação devem utilizar CI/CD.
- **Bastion Host:**
  - **NÃO** deve rodar em uma rede publicamente acessível.
  - **NÃO** deve hospedar o banco de dados da aplicação.
  - **DEVE** usar Puppet para gerenciar usuários do sistema.
  - **DEVE** hospedar ferramentas não críticas (ex.: pgAdmin).

## Entregáveis

- Repositório(s) no GitLab/GitHub contendo:
  - A aplicação web
  - Dockerfiles (incluindo scripts de entrypoint)
  - Código Puppet
  - Qualquer outro código relacionado
- Diagrama da infraestrutura
- Guias de uso para:
  - Desenvolvedores da aplicação
  - Usuários administradores