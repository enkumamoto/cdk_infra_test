import aws_cdk as core
import aws_cdk.assertions as assertions

from cdk_infra_test.cdk_infra_test_stack import CdkInfraTestStack


def test_infra_resources_created():
    app = core.App()
    stack = CdkInfraTestStack(app, "cdk-infra-test")
    template = assertions.Template.from_stack(stack)
    
    template.resource_count_is("AWS::EC2::VPC", 1)
    template.resource_count_is("AWS::EC2::Subnet", 4)  # 2 public + 2 private (max_azs=2)
    
    template.has_resource_properties("AWS::S3::Bucket", {
        "VersioningConfiguration": {"Status": "Enabled"},
        "PublicAccessBlockConfiguration": {
            "BlockPublicAcls": True,
            "BlockPublicPolicy": True,
            "IgnorePublicAcls": True,
            "RestrictPublicBuckets": True
        }
    })
    
    template.resource_count_is("AWS::EC2::Instance", 1)
    
    template.resource_count_is("AWS::RDS::DBCluster", 1)

    template.has_resource_properties("AWS::RDS::DBCluster", {
        "Engine": "aurora-postgresql"
    })
    
    template.resource_count_is("AWS::ECR::Repository", 1)
    
    template.resource_count_is("AWS::ECS::Cluster", 1)
    template.resource_count_is("AWS::ECS::Service", 1)
    template.resource_count_is("AWS::ECS::TaskDefinition", 1)
    
    template.resource_count_is("AWS::ElasticLoadBalancingV2::LoadBalancer", 1)
    template.resource_count_is("AWS::ElasticLoadBalancingV2::Listener", 1)
    template.resource_count_is("AWS::ElasticLoadBalancingV2::TargetGroup", 1)
    
    template.resource_count_is("AWS::EC2::ClientVpnEndpoint", 1)
    template.resource_count_is("AWS::EC2::ClientVpnTargetNetworkAssociation", 1)
    template.resource_count_is("AWS::EC2::ClientVpnAuthorizationRule", 1)
    
    template.has_output("ApplicationURL", {})
    template.has_output("BastionInstanceID", {})
    template.has_output("DatabaseClusterEndpoint", {})
    template.has_output("DatabaseName", {})
    template.has_output("DatabaseSecretArn", {})
    template.has_output("PuppetBucketName", {})
    template.has_output("VpnEndpointId", {})
