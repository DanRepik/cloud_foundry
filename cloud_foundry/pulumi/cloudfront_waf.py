from typing import List
from constructs import Construct

from imports.aws.data_aws_wafv2_ip_set import DataAwsWafv2IpSet
from imports.aws.wafv2_web_acl import Wafv2WebAcl, Wafv2WebAclRule

from ..lib.common import make_id, make_resource, make_tags


class CloudFrontWAF(Construct):
    def __init__(self, scope: Construct, id: str):
        super().__init__(scope, make_id(scope, id))

        # Create the AWS WAF WebACL
        self.waf = Wafv2WebAcl(
            scope,
            make_id(scope, f"{id}-waf"),
            name=make_resource(scope, f"{id}-waf"),
            scope="CLOUDFRONT",
            description="AWS CF WAF",
            default_action={"allow": {}},
            rule=[*self.access_white_list(scope, id)],
            visibility_config={
                "cloudwatch_metrics_enabled": True,
                "metric_name": "DefaultAllowMetric",
                "sampled_requests_enabled": True,
            },
            tags=make_tags(scope, f"{id}-waf"),
        )

    def access_white_list(self, scope: Construct, id: str):
        dev_access_ip_set = DataAwsWafv2IpSet(
            scope,
            make_id(scope, f"{id}-ip-set"),
            name=scope.config.get("access_white_list", "DevAccessWhiteList"),
            scope="CLOUDFRONT",
        )

        # Define rules for DevAccessWhiteList
        return [
            Wafv2WebAclRule(
                name="AllowDevAccess",
                priority=0,
                statement={
                    "ip_set_reference_statement": {"arn": dev_access_ip_set.arn}
                },
                action={"allow": {}},
                visibility_config={
                    "sampled_requests_enabled": True,
                    "cloudwatch_metrics_enabled": True,
                    "metric_name": "AllowDev",
                },
            )
        ]

    def default_rule_set(self):
        return [
            {
                "name": "AWSRateBasedRuleDOS",
                "priority": 1,
                "action": {
                    "block": {},
                },
                "statement": {
                    "rateBased_statement": {
                        "limit": 2000,
                        "aggregate_key_type": "IP",
                    },
                },
                "visibility_config": {
                    "cloudwatch_metrics_enabled": True,
                    "metric_name": "AWSRateBasedRuleDOSMetric",
                    "sampled_requests_enabled": True,
                },
            },
            {
                "name": "AWS-AWSManagedRulesAmazonIpReputationList",
                "priority": 10,
                "override_action": {
                    "none": {},
                },
                "statement": {
                    "managed_rule_group_statement": {
                        "name": "AWSManagedRulesAmazonIpReputationList",
                        "vendor_name": "AWS",
                    },
                },
                "visibility_config": {
                    "cloudwatch_metrics_enabled": True,
                    "metric_name": "AWSManagedRulesAmazonIpReputationListMetric",
                    "sampled_requests_enabled": True,
                },
            },
            {
                "name": "AWS-AWSManagedRulesAnonymousIpList",
                "priority": 20,
                "override_action": {
                    "none": {},
                },
                "statement": {
                    "managed_rule_group_statement": {
                        "name": "AWSManagedRulesAnonymousIpList",
                        "vendor_name": "AWS",
                    },
                },
                "visibility_config": {
                    "cloudwatch_metrics_enabled": True,
                    "metric_name": "AWSManagedRulesAnonymousIpListMetric",
                    "sampled_requests_enabled": True,
                },
            },
            {
                "name": "AWS-AWSManagedRulesCommonRuleSet",
                "priority": 30,
                "override_action": {
                    "none": {},
                },
                "statement": {
                    "managed_rule_group_statement": {
                        "name": "AWSManagedRulesCommonRuleSet",
                        "vendor_name": "AWS",
                    },
                },
                "visibility_config": {
                    "cloudwatch_metrics_enabled": True,
                    "metric_name": "AWSManagedRulesCommonRuleSetMetric",
                    "sampled_requests_enabled": True,
                },
            },
            {
                "name": "AWS-AWSManagedRulesKnownBadInputsRuleSet",
                "priority": 40,
                "override_action": {
                    "none": {},
                },
                "statement": {
                    "managed_rule_group_statement": {
                        "name": "AWSManagedRulesKnownBadInputsRuleSet",
                        "vendor_name": "AWS",
                    },
                },
                "visibility_config": {
                    "cloudwatch_metrics_enabled": True,
                    "metric_name": "AWSManagedRulesKnownBadInputsRuleSetMetric",
                    "sampled_requests_enabled": True,
                },
            },
            {
                "name": "AWS-AWSManagedRulesSQLiRuleSet",
                "priority": 50,
                "override_action": {
                    "none": {},
                },
                "statement": {
                    "managed_rule_group_statement": {
                        "name": "AWSManagedRulesSQLiRuleSet",
                        "vendor_name": "AWS",
                    },
                },
                "visibility_config": {
                    "cloudwatch_metrics_enabled": True,
                    "metric_name": "AWSManagedRulesSQLiRuleSetMetric",
                    "sampled_requests_enabled": True,
                },
            },
            {
                "name": "AWS-AWSManagedRulesBotControlRuleSet",
                "priority": 60,
                "override_action": {
                    "count": {},
                },
                "statement": {
                    "managed_rule_group_statement": {
                        "name": "AWSManagedRulesBotControlRuleSet",
                        "vendor_name": "AWS",
                    },
                },
                "visibility_config": {
                    "cloudwatch_metrics_enabled": True,
                    "metric_name": "AWSManagedRulesBotControlRuleSetMetric",
                    "sampled_requests_enabled": True,
                },
            },
        ]
