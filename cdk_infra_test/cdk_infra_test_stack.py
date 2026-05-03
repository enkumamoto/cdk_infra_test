from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_rds as rds,
    aws_ecs as ecs,
    aws_ecr as ecr,
    aws_s3 as s3,
    aws_elasticloadbalancingv2 as elbv2,
    aws_acmpca as acmpca,
    aws_certificatemanager as acm,
    aws_cloudwatch as cloudwatch,
    aws_logs as logs,
    CfnOutput,
)
from constructs import Construct


class CdkInfraTestStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        # === PRIVATE CA ===
        vpn_ca = acmpca.CfnCertificateAuthority(
            self,
            "VpnPrivateCA",
            type="ROOT",
            key_algorithm="RSA_2048",
            signing_algorithm="SHA384withRSA",
            subject=acmpca.CfnCertificateAuthority.SubjectProperty(
                country="BR",
                organization="DevOpsTest",
                organizational_unit="IT",
                common_name="vpn.devops.local",
            ),
        )

        ca_certificate = acmpca.CfnCertificate(
            self,
            "VpnPrivateCACertificate",
            certificate_authority_arn=vpn_ca.attr_arn,
            certificate_signing_request=vpn_ca.attr_certificate_signing_request,
            signing_algorithm="SHA384withRSA",
            template_arn="arn:aws:acm-pca:::template/RootCACertificate/V1",
            validity=acmpca.CfnCertificate.ValidityProperty(
                type="YEARS",
                value=10,
            ),
        )

        acmpca.CfnCertificateAuthorityActivation(
            self,
            "VpnPrivateCAActivation",
            certificate_authority_arn=vpn_ca.attr_arn,
            certificate=ca_certificate.attr_certificate,
            status="ACTIVE",
        )

        server_cert = acm.Certificate(
            self,
            "VpnServerCert",
            domain_name="vpn-server.devopstest.local",
        )

        client_cert = acm.Certificate(
            self,
            "VpnClientCert",
            domain_name="vpn-client.devopstest.local",
        )

        # === S3 PUPPET BUCKET ===
        self.puppet_bucket = s3.Bucket(
            self,
            "PuppetBucket",
            versioned=True,
            removal_policy=RemovalPolicy.RETAIN,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            lifecycle_rules=[
                s3.LifecycleRule(
                    noncurrent_version_expiration=Duration.days(90),
                )
            ],
        )

        # === VPC ===
        self.vpc = ec2.Vpc(
            self,
            "VPCDevOpsTest",
            max_azs=2,
            nat_gateways=2,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24,
                ),
            ],
        )

        # VPC Flow Logs para auditoria e troubleshooting
        self.vpc.add_flow_log(
            "VpcFlowLog",
            traffic_type=ec2.FlowLogTrafficType.ALL,
        )

        # === VPN ===
        vpn_sg = ec2.SecurityGroup(
            self,
            "VpnSG",
            vpc=self.vpc,
            description="SG for VPN Connections",
            allow_all_outbound=True,
        )

        # Log do grupo para conexões VPN
        vpn_log_group = logs.LogGroup(
            self,
            "VpnConnectionLogs",
            retention=logs.RetentionDays.THREE_MONTHS,
            removal_policy=RemovalPolicy.RETAIN,
        )

        client_vpn = ec2.CfnClientVpnEndpoint(
            self,
            "ClientVpnEndpoint",
            authentication_options=[
                ec2.CfnClientVpnEndpoint.ClientAuthenticationRequestProperty(
                    type="certificate-authentication",
                    mutual_authentication=ec2.CfnClientVpnEndpoint.CertificateAuthenticationRequestProperty(
                        client_root_certificate_chain_arn=client_cert.certificate_arn,
                    ),
                ),
            ],
            client_cidr_block="10.100.0.0/22",
            connection_log_options=ec2.CfnClientVpnEndpoint.ConnectionLogOptionsProperty(
                enabled=True,
                cloudwatch_log_group=vpn_log_group.log_group_name,
            ),
            server_certificate_arn=server_cert.certificate_arn,
            vpc_id=self.vpc.vpc_id,
            security_group_ids=[vpn_sg.security_group_id],
            split_tunnel=True,
            transport_protocol="udp",
        )

        ec2.CfnClientVpnTargetNetworkAssociation(
            self,
            "VpnAssociation",
            client_vpn_endpoint_id=client_vpn.ref,
            subnet_id=self.vpc.private_subnets[0].subnet_id,
        )

        ec2.CfnClientVpnAuthorizationRule(
            self,
            "VpnAuthRule",
            client_vpn_endpoint_id=client_vpn.ref,
            target_network_cidr=self.vpc.vpc_cidr_block,
            authorize_all_groups=True,
        )

        # === BASTION ===
        bastion_sg = ec2.SecurityGroup(
            self,
            "BastionSG",
            vpc=self.vpc,
            description="SG for Bastion Hosts",
            allow_all_outbound=True,
        )

        bastion_sg.add_ingress_rule(
            peer=vpn_sg,
            connection=ec2.Port.tcp(22),
            description="Allow VPN access to Bastion via SSH",
        )

        bastion_role = iam.Role(
            self,
            "BastionRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
        )

        bastion_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "AmazonSSMManagedInstanceCore"
            )
        )

        ami = ec2.MachineImage.latest_amazon_linux2023()

        self.bastion_host = ec2.Instance(
            self,
            "BastionHost",
            vpc=self.vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            instance_type=ec2.InstanceType("t3.small"),
            machine_image=ami,
            security_group=bastion_sg,
            role=bastion_role,
            require_imdsv2=True,
        )

        self.puppet_bucket.grant_read(self.bastion_host.role)

        self.bastion_host.add_user_data(
            "yum install -y amazon-ssm-agent",
            "systemctl enable amazon-ssm-agent",
            "systemctl start amazon-ssm-agent",
            "yum install -y puppet",
            "cd /home/ec2-user",
            f"aws s3 sync s3://{self.puppet_bucket.bucket_name}/puppet /opt/puppet",
            "puppet apply /opt/puppet/manifests/site.pp",
        )

        # === RDS ===
        db_sg = ec2.SecurityGroup(
            self,
            "DatabaseSG",
            vpc=self.vpc,
            description="SG for Database",
        )

        db_sg.add_ingress_rule(
            peer=bastion_sg,
            connection=ec2.Port.tcp(5432),
            description="Allow Bastion access to PostgreSQL",
        )

        db_subnet_group = rds.SubnetGroup(
            self,
            "DataBaseSubnetGroup",
            description="Database Subnet Group",
            vpc=self.vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            removal_policy=RemovalPolicy.RETAIN,
        )

        # Role para enhanced monitoring do RDS
        rds_monitoring_role = iam.Role(
            self,
            "RdsMonitoringRole",
            assumed_by=iam.ServicePrincipal("monitoring.rds.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AmazonRDSEnhancedMonitoringRole"
                )
            ],
        )

        self.db_cluster = rds.DatabaseCluster(
            self,
            "DatabaseCluster",
            engine=rds.DatabaseClusterEngine.aurora_postgres(
                version=rds.AuroraPostgresEngineVersion.VER_14_6
            ),
            writer=rds.ClusterInstance.serverless_v2("writer"),
            readers=[
                rds.ClusterInstance.serverless_v2("reader")
            ],
            vpc=self.vpc,
            subnet_group=db_subnet_group,
            security_groups=[db_sg],
            credentials=rds.Credentials.from_generated_secret("postgres"),
            default_database_name="appdb",
            serverless_v2_min_capacity=0.5,
            serverless_v2_max_capacity=8,
            deletion_protection=True,
            removal_policy=RemovalPolicy.SNAPSHOT,
            backup=rds.BackupProps(retention=Duration.days(7)),
            cloudwatch_logs_exports=["postgresql"],
            monitoring_interval=Duration.seconds(60),
            monitoring_role=rds_monitoring_role,
            storage_encrypted=True,
        )

        # === ECR ===
        self.ecr_repo = ecr.Repository(
            self,
            "AppRepository",
            removal_policy=RemovalPolicy.RETAIN,
            image_scan_on_push=True,
            lifecycle_rules=[
                # Mantém as 10 imagens mais recentes por tag; remove untagged após 1 dia
                ecr.LifecycleRule(
                    description="Remove untagged images after 1 day",
                    max_image_age=Duration.days(1),
                    tag_status=ecr.TagStatus.UNTAGGED,
                ),
                ecr.LifecycleRule(
                    description="Keep last 10 tagged images",
                    max_image_count=10,
                    tag_status=ecr.TagStatus.ANY,
                ),
            ],
        )

        # === ECS CLUSTER ===
        self.ecs_cluster = ecs.Cluster(
            self,
            "AppCluster",
            vpc=self.vpc,
            container_insights=True,
        )

        # === ECS SECURITY GROUP ===
        ecs_sg = ec2.SecurityGroup(
            self,
            "EcsSG",
            vpc=self.vpc,
            description="SG for ECS",
            allow_all_outbound=True,
        )

        self.db_cluster.connections.allow_from(
            ecs_sg,
            ec2.Port.tcp(5432),
            description="Allow ECS to access DB",
        )

        # === ECS EXECUTION ROLE (pull image + inject secrets) ===
        execution_role = iam.Role(
            self,
            "EcsExecutionRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
        )

        execution_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "service-role/AmazonECSTaskExecutionRolePolicy"
            )
        )

        # === ECS TASK ROLE (permissões mínimas para a aplicação) ===
        task_role = iam.Role(
            self,
            "EcsTaskRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
        )

        # Apenas escrita de logs — sem acesso a secrets ou serviços não necessários
        task_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["logs:CreateLogStream", "logs:PutLogEvents"],
                resources=["*"],
            )
        )

        # === TASK DEFINITION ===
        task_def = ecs.FargateTaskDefinition(
            self,
            "AppTaskDef",
            memory_limit_mib=1024,
            cpu=512,
            task_role=task_role,
            execution_role=execution_role,
        )

        # === CONTAINER ===
        container = task_def.add_container(
            "FastAPIContainer",
            image=ecs.ContainerImage.from_ecr_repository(self.ecr_repo, tag="latest"),
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="fastapi",
                log_retention=logs.RetentionDays.ONE_MONTH,
            ),
            environment={
                "DB_NAME": "appdb",
                "DB_HOST": self.db_cluster.cluster_endpoint.hostname,
            },
            secrets={
                "DB_USER": ecs.Secret.from_secrets_manager(
                    self.db_cluster.secret,
                    field="username",
                ),
                "DB_PASSWORD": ecs.Secret.from_secrets_manager(
                    self.db_cluster.secret,
                    field="password",
                ),
            },
            health_check=ecs.HealthCheck(
                command=["CMD-SHELL", "curl -f http://localhost:8000/health || exit 1"],
                interval=Duration.seconds(30),
                timeout=Duration.seconds(5),
                retries=3,
                start_period=Duration.seconds(60),
            ),
        )

        container.add_port_mappings(
            ecs.PortMapping(
                container_port=8000,
                host_port=8000,
                protocol=ecs.Protocol.TCP,
            )
        )

        # === ALB ===
        alb = elbv2.ApplicationLoadBalancer(
            self,
            "AppALB",
            vpc=self.vpc,
            internet_facing=True,
            deletion_protection=True,
        )

        listener = alb.add_listener(
            "HttpListener",
            port=80,
            open=True,
        )

        # === ECS SERVICE ===
        service = ecs.FargateService(
            self,
            "AppService",
            cluster=self.ecs_cluster,
            task_definition=task_def,
            desired_count=2,
            assign_public_ip=False,
            security_groups=[ecs_sg],
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
            min_healthy_percent=50,
            max_healthy_percent=200,
        )

        listener.add_targets(
            "EcsTargets",
            port=8000,
            protocol=elbv2.ApplicationProtocol.HTTP,
            targets=[service],
            health_check=elbv2.HealthCheck(
                path="/health",
                interval=Duration.seconds(30),
                healthy_threshold_count=2,
                unhealthy_threshold_count=3,
            ),
            deregistration_delay=Duration.seconds(30),
        )

        # === AUTO-SCALING ===
        scaling = service.auto_scale_task_count(min_capacity=2, max_capacity=10)

        scaling.scale_on_cpu_utilization(
            "CpuScaling",
            target_utilization_percent=70,
            scale_in_cooldown=Duration.seconds(300),
            scale_out_cooldown=Duration.seconds(60),
        )

        scaling.scale_on_memory_utilization(
            "MemoryScaling",
            target_utilization_percent=80,
            scale_in_cooldown=Duration.seconds(300),
            scale_out_cooldown=Duration.seconds(60),
        )

        # === CLOUDWATCH ALARMS ===
        cloudwatch.Alarm(
            self,
            "EcsCpuAlarm",
            metric=service.metric_cpu_utilization(),
            threshold=85,
            evaluation_periods=3,
            datapoints_to_alarm=2,
            alarm_description="ECS CPU acima de 85% — considere escalar manualmente",
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )

        cloudwatch.Alarm(
            self,
            "EcsMemoryAlarm",
            metric=service.metric_memory_utilization(),
            threshold=90,
            evaluation_periods=3,
            datapoints_to_alarm=2,
            alarm_description="ECS Memory acima de 90%",
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )

        cloudwatch.Alarm(
            self,
            "AlbUnhealthyHostsAlarm",
            metric=listener.metric_target_response_time(),
            threshold=2,
            evaluation_periods=2,
            alarm_description="Latência do ALB acima de 2s",
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )

        # === OUTPUTS ===
        CfnOutput(
            self,
            "ApplicationURL",
            value=f"http://{alb.load_balancer_dns_name}",
            description="Public URL of the FastAPI application",
        )

        CfnOutput(
            self,
            "BastionInstanceID",
            value=self.bastion_host.instance_id,
            description="Bastion Instance ID",
        )

        CfnOutput(
            self,
            "DatabaseClusterEndpoint",
            value=self.db_cluster.cluster_endpoint.hostname,
            description="Database Cluster Endpoint",
        )

        CfnOutput(
            self,
            "DatabaseName",
            value="appdb",
            description="Database name",
        )

        CfnOutput(
            self,
            "DatabaseSecretArn",
            value=self.db_cluster.secret.secret_arn,
            description="Secret ARN for database credentials",
        )

        CfnOutput(
            self,
            "EcsClusterName",
            value=self.ecs_cluster.cluster_name,
            description="ECS Cluster Name",
        )

        CfnOutput(
            self,
            "EcsServiceName",
            value=service.service_name,
            description="ECS Service Name",
        )

        CfnOutput(
            self,
            "EcrRepositoryUri",
            value=self.ecr_repo.repository_uri,
            description="ECR Repository URI",
        )

        CfnOutput(
            self,
            "PuppetBucketName",
            value=self.puppet_bucket.bucket_name,
        )

        CfnOutput(
            self,
            "VpnEndpointId",
            value=client_vpn.ref,
            description="Client VPN Endpoint ID",
        )
