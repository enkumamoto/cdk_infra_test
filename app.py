#!/usr/bin/env python3
import os

import aws_cdk as cdk

from cdk_infra_test.cdk_infra_test_stack import CdkInfraTestStack


app = cdk.App()
CdkInfraTestStack(
    app, 
    "CdkInfraTestStack",
    )

app.synth()
