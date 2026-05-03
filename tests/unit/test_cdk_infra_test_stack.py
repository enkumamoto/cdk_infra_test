import aws_cdk as core
import aws_cdk.assertions as assertions

from cdk_infra_test.cdk_infra_test_stack import CdkInfraTestStack


def test_infra_resources_created():
    app = core.App()
    stack = CdkInfraTestStack(app, "cdk-infra-test")
    template = assertions.Template.from_stack(stack)

    template.resource_count_is("AWS::EC2::VPC", 1)
    template.resource_count_is("AWS::EC2::Subnet", 4)  # 2 public + 2 private

    template.has_resource_properties("AWS::S3::Bucket", {
        "VersioningConfiguration": {"Status": "Enabled"},
        "PublicAccessBlockConfiguration": {
            "BlockPublicAcls": True,
            "BlockPublicPolicy": True,
            "IgnorePublicAcls": True,
            "RestrictPublicBuckets": True,
        },
    })

    template.resource_count_is("AWS::EC2::Instance", 1)

    template.resource_count_is("AWS::RDS::DBCluster", 1)

    template.has_resource_properties("AWS::RDS::DBCluster", {
        "Engine": "aurora-postgresql",
        "DeletionProtection": True,
        "StorageEncrypted": True,
        "BackupRetentionPeriod": 7,
        "EnableCloudwatchLogsExports": ["postgresql"],
    })

    template.resource_count_is("AWS::ECR::Repository", 1)

    template.resource_count_is("AWS::ECS::Cluster", 1)

    template.has_resource_properties("AWS::ECS::Cluster", {
        "ClusterSettings": [{"Name": "containerInsights", "Value": "enabled"}],
    })

    template.resource_count_is("AWS::ECS::Service", 1)

    template.has_resource_properties("AWS::ECS::Service", {
        "DesiredCount": 2,
        "DeploymentConfiguration": {
            "DeploymentCircuitBreaker": {"Enable": True, "Rollback": True},
        },
    })

    template.resource_count_is("AWS::ECS::TaskDefinition", 1)

    template.has_resource_properties("AWS::ECS::TaskDefinition", {
        "Cpu": "512",
        "Memory": "1024",
    })

    template.resource_count_is("AWS::ElasticLoadBalancingV2::LoadBalancer", 1)

    template.has_resource_properties("AWS::ElasticLoadBalancingV2::LoadBalancer", {
        "LoadBalancerAttributes": assertions.Match.array_with([
            {"Key": "deletion_protection.enabled", "Value": "true"},
        ]),
    })

    template.resource_count_is("AWS::ElasticLoadBalancingV2::Listener", 1)
    template.resource_count_is("AWS::ElasticLoadBalancingV2::TargetGroup", 1)

    template.resource_count_is("AWS::EC2::ClientVpnEndpoint", 1)
    template.resource_count_is("AWS::EC2::ClientVpnTargetNetworkAssociation", 1)
    template.resource_count_is("AWS::EC2::ClientVpnAuthorizationRule", 1)

    # CloudWatch alarms
    template.resource_count_is("AWS::CloudWatch::Alarm", 3)

    # Auto-scaling
    template.resource_count_is("AWS::ApplicationAutoScaling::ScalableTarget", 1)
    template.resource_count_is("AWS::ApplicationAutoScaling::ScalingPolicy", 2)

    template.has_output("ApplicationURL", {})
    template.has_output("BastionInstanceID", {})
    template.has_output("DatabaseClusterEndpoint", {})
    template.has_output("DatabaseName", {})
    template.has_output("DatabaseSecretArn", {})
    template.has_output("EcrRepositoryUri", {})
    template.has_output("PuppetBucketName", {})
    template.has_output("VpnEndpointId", {})
