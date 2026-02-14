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
    aws_iam as iam,
    aws_elasticloadbalancingv2 as elbv2,
    CfnOutput,
)
from constructs import Construct


class CdkInfraTestStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)
        
        # Certificate
        server_certificate_arn = self.node.try_get_context("server_certificate_arn")
        client_certificate_arn = self.node.try_get_context("client_certificate_arn")
        
        if not server_certificate_arn or not client_certificate_arn:
            raise ValueError("Inform certificates (Server and Client)")
        
        # S3 Bucket
        self.puppet_bucket = s3.Bucket(
            self,
            "PuppetBucket",
            bucket_name="puppet-bucket",
            versioned=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )

        # VPC
        self.vpc = ec2.Vpc(
            self,
            "VPCDevOpsTest",
            max_azs=2,
            nat_gateways=1,
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
        
        # VPN Sg
        vpn_sg = ec2.SecurityGroup(
            self,
            "VpnSG",
            vpc=self.vpc,
            description="SG for VPN Connections",
            allow_all_outbound=True,
        )
        
        # VPN Client
        client_vpn = ec2.CfnClientVpnEndpoint(
            self,
            "ClientVpnEndpoint",
            authentication_options=[
                ec2.CfnClientVpnEndpoint.ClientAuthenticationRequestProperty(
                    type="certificate-authentication",
                    mutual_authentication=ec2.CfnClientVpnEndpoint.CertificateAuthenticationRequestProperty(
                        client_root_certificate_chain_arn=client_certificate_arn
                        ),
                    )
                ],
            client_cidr_block="10.100.0.0/22",
            connection_log_options=ec2.CfnClientVpnEndpoint.ConnectionLogOptionsProperty(
                enabled=False,
                ),
            server_certificate_arn=server_certificate_arn,
            vpc_id=self.vpc.vpc_id,
            security_group_ids=[vpn_sg.security_group_id],
            split_tunnel=True,
            transport_protocol="udp",
        )
        
        # Private Subnet VPN Association
        ec2.CfnClientVpnTargetNetworkAssociation(
            self,
            "VpnAssociation",
            client_vpn_endpoint_id=client_vpn.ref,
            subnet_id=self.vpc.private_subnets[0].subnet_id,
        )
        
        # VPN Access Auth
        ec2.CfnClientVpnAuthorizationRule(
            self,
            "VpnAuthRule",
            client_vpn_endpoint_id=client_vpn.ref,
            target_network_cidr_block=self.vpc.vpc_cidr_block,
            authorize_all_groups=True,
        )
            
        
        # Bastion SG
        bastion_sg = ec2.SecurityGroup(
            self,
            "BastionSG",
            vpc=self.vpc,
            description="SG for Bastion Hosts",
            allow_all_outbound=True,
        )
        
        bastion_sg.add_ingress_rule(
            peer = vpn_sg,
            connection = ec2.Port.tcp(22),
            description="Allow VPN access to Bastion via SSH",
        )
        
        # Bastion Role
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
        
        # Bastion Host
        ami = ec2.MachineImage.latest_amazon_linux2023()
        
        self.bastion_host = ec2.Instance(
            self,
            "BastionHost",
            vpc=self.vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
                ),
            instance_type=ec2.InstanceType("t3.micro"),
            machine_image=ami,
            security_group=bastion_sg,
            role=bastion_role,
        )
        
        self.puppet_bucket.grant_read(self.bastion_host.role)
        
        self.bastion_host.add_user_data(
            "yum install -y amazon-ssm-agent",
            "systemctl enable amazon-ssm-agent",
            "systemctl start amazon-ssm-agent",
            "yum install -y puppet",
            "cd /home/ec2-user",
            f"aws s3 sync s3://{self.puppet_bucket.bucket_name}/puppet /opt/puppet",
            "puppet apply puppet/manifests/site.pp"
        )
        
        # RDS SG
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
             
        # RDS Private Subnet
        db_subnet_group = rds.SubnetGroup (
            self,
            "DataBaseSubnetGroup",
            description = "Database Subnet Group",
            vpc=self.vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
                ),
            removal_policy=RemovalPolicy.DESTROY,
        
        )
        
        # RDS Cluster
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
            credentials = rds.Credentials.from_generated_secret("postres"),
            default_database_name="appdb",
            serverless_v2_min_capacity = 0.5,
            serverless_v2_max_capacity = 1,
            removal_policy=RemovalPolicy.DESTROY,   
        )
        
        # ECR
        self.ecr_repo = ecr.Repository(
            self,
            "AppRepository",
            removal_policy=RemovalPolicy.DESTROY,
            image_scan_on_push=True,
        )
        
        # ECS CLuster
        self.ecs_cluster = ecs.Cluster(
            self,
            "AppCluster",
            vpc=self.vpc,
        )
        
        # ECS Security Group
        ecs_sg = ec2.SecurityGroup(
            self,
            "EcsSG",
            vpc=self.vpc,
            description="SG for ECS",
            allow_all_outbound=True,
        )
        
        # Allow ECS to access DB
        self.db_cluster.connections.allow_from(
            ecs_sg,
            ec2.Port.tcp(5432),
            description="Allow ECS to access DB",
        )
        
        # Task Role
        task_role = iam.Role(
            self,
            "EcsTaskRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
        )
        
        task_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "AmazonECSTaskExecutionRolePolicy"
            )
        )
        
        task_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "SecretsManagerReadWrite"
            )
        )
        
        # Task Definition
        task_def = ecs.FargateTaskDefinition(
            self,
            "AppTaskDef",
            memory_limit_mib=512,
            cpu=256,
            task_role=task_role,
        )
        
        # Container
        container = task_def.add_container(
            "FastAPIContainer",
            image=ecs.ContainerImage.from_ecr_repository(self.ecr_repo, tag="latest"),
            logging=ecs.LogDrivers.aws_logs(stream_prefix="fastapi"),
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
        )
        
        container.add_port_mappings(
            ecs.PortMapping(
                container_port=8000,
                host_port=8000,
                protocol=ecs.Protocol.TCP,
            )
        )
        
        # ALB
        alb = elbv2.ApplicationLoadBalancer(
            self,
            "AppALB",
            vpc=self.vpc,
            internet_facing=True,
        )

        listener = alb.add_listener(
            "HttpListener",
            port=80,
            open=True,
        )

        # ECS Service
        service = ecs.FargateService(
            self,
            "AppService",
            cluster=self.ecs_cluster,
            task_definition=task_def,
            desired_count=1,
            assign_public_ip=False,
            security_groups=[ecs_sg],
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
        )

        listener.add_targets(
            "EcsTargets",
            port=80,
            targets=[service],
            health_check=elbv2.HealthCheck(
                path="/health",
                interval=Duration.seconds(30),
            ),
        )
        
        # IAM

        # Output URL
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
            description="Database name"
        )
        
        CfnOutput(
            self,
            "DatabaseSecretArn",
            value=self.db_cluster.secret.secret_arn,
            description="Secret ARN for database credentials"
        )
        
        CfnOutput(
            self, 
            "PuppetBucketName", 
            value=self.puppet_bucket.bucket_name
        )
        
        CfnOutput(
            self,
            "VpnEndpointId",
            value=client_vpn.ref,
            description="Client VPN Endpoint ID",
        )
