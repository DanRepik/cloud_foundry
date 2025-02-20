# api_waf.py
import json
from typing import Optional

import pulumi
from pulumi_aws import wafv2

from cloud_foundry.utils.logger import logger

log = logger(__name__)


class RestAPIFirewall:
    def __init__(
        self,
        *,
        default_action: Optional[dict] = None,
        visibility_config: Optional[dict] = None,
        common_set: Optional[bool] = True,
        block_sql_injection: Optional[bool] = False,
        block_xss: Optional[bool] = False,
        rate_limit: Optional[int] = None,
        allowed_cidr_blocks: Optional[list[str]] = None,
    ):
        """
        :param default_action: Defines the default behavior for requests not matching any rules. For example,
                               `{"allow": {}}` allows all unmatched requests, whereas `{"block": {}}` blocks them.
        :param visibility_config: Configuration for logging and metrics. Includes settings for CloudWatch metrics and
                                  request sampling.
        :param block_sql_injection: Enables or disables blocking of SQL injection attacks.
        :param block_xss: Enables or disables blocking of Cross-Site Scripting (XSS) attacks.
        :param rate_limit: Specifies a request rate limit in requests per 5-minute period. Requests exceeding this
                           threshold will be blocked.
        :param allowed_cidr_blocks: A list of CIDR blocks specifying trusted IP ranges that should always be allowed.
        """
        # Default action configuration, e.g., allow all or block all unmatched requests.
        self.default_action = default_action or {"allow": {}}

        # Visibility configuration for CloudWatch logging and metrics.
        self.visibility_config = visibility_config or {
            "cloudwatch_metrics_enabled": True,
            "metric_name": "gatewayRestApiWebAclMetric",
            "sampled_requests_enabled": True,
        }

        self.common_set = common_set
        # Configuration for SQL injection and XSS protections.
        self.block_sql_injection = block_sql_injection
        self.block_xss = block_xss

        # Rate limiting threshold.
        self.rate_limit = rate_limit

        # CIDR blocks representing trusted IP ranges.
        self.allowed_cidr_blocks = allowed_cidr_blocks


class GatewayRestApiWAF:
    def __init__(
        self, name: str, firewall: Optional[RestAPIFirewall] = RestAPIFirewall()
    ):
        """
        :param name: Name of the WAF instance.
        :param description: A description of the WAF and its purpose.
        :param firewall: An instance of RestAPIFirewall containing configuration details for rules.
        """
        # List to store WAF rules.
        rules = []
        priority = 1  # Priority for rule evaluation order.

        if firewall.common_set:
            # Add a rule to block SQL injection attacks using AWS Managed Rules.
            rules.append(
                wafv2.WebAclRuleArgs(
                    name="commonSet",
                    priority=priority,
                    action=wafv2.WebAclRuleActionArgs(block={}),
                    #                    override_action=wafv2.WebAclRuleOverrideActionArgs(none=None),
                    visibility_config=wafv2.WebAclRuleVisibilityConfigArgs(
                        cloudwatch_metrics_enabled=True,
                        metric_name="commonSetMetric",
                        sampled_requests_enabled=True,
                    ),
                    statement=wafv2.WebAclRuleStatementArgs(
                        managed_rule_group_statement=wafv2.WebAclRuleStatementManagedRuleGroupStatementArgs(
                            vendor_name="AWS",
                            name="AWSManagedRulesCommonRuleSet",
                        )
                    ),
                )
            )
            priority += 1

        if firewall.block_sql_injection:
            # Add a rule to block SQL injection attacks using AWS Managed Rules.
            rules.append(
                wafv2.WebAclRuleArgs(
                    name="blockSQLInjection",
                    priority=priority,
                    action=wafv2.WebAclRuleActionArgs(block={}),
                    visibility_config=wafv2.WebAclRuleVisibilityConfigArgs(
                        cloudwatch_metrics_enabled=True,
                        metric_name="blockSQLInjectionMetric",
                        sampled_requests_enabled=True,
                    ),
                    statement=wafv2.WebAclRuleStatementArgs(
                        managed_rule_group_statement=wafv2.WebAclRuleStatementManagedRuleGroupStatementArgs(
                            vendor_name="AWS",
                            name="AWSManagedRulesSQLiRuleSet",
                        )
                    ),
                )
            )
            priority += 1

        if firewall.block_xss:
            # Add a rule to block XSS attacks using AWS Managed Rules.
            rules.append(
                wafv2.WebAclRuleArgs(
                    name="blockXSS",
                    priority=priority,
                    action=wafv2.WebAclRuleActionArgs(block={}),
                    visibility_config=wafv2.WebAclRuleVisibilityConfigArgs(
                        cloudwatch_metrics_enabled=True,
                        metric_name="blockXSSMetric",
                        sampled_requests_enabled=True,
                    ),
                    statement=wafv2.WebAclRuleStatementArgs(
                        managed_rule_group_statement=wafv2.WebAclRuleStatementManagedRuleGroupStatementArgs(
                            name="AWSManagedRulesXSSRuleSet", vendor_name="AWS"
                        )
                    ),
                )
            )
            priority += 1

        if firewall.rate_limit:
            # Add a rate-limiting rule to block excessive requests based on IP.
            rules.append(
                wafv2.WebAclRuleArgs(
                    name="rateLimitRule",
                    priority=priority,
                    action=wafv2.WebAclRuleActionArgs(block={}),
                    visibility_config=wafv2.WebAclRuleVisibilityConfigArgs(
                        cloudwatch_metrics_enabled=True,
                        metric_name="rateLimitRuleMetric",
                        sampled_requests_enabled=True,
                    ),
                    statement=wafv2.WebAclRuleStatementArgs(
                        rate_based_statement=wafv2.WebAclRuleStatementRateBasedStatementArgs(
                            limit=firewall.rate_limit, aggregate_key_type="IP"
                        )
                    ),
                )
            )
            priority += 1

        if firewall.allowed_cidr_blocks:
            # Create an IP set for trusted IPs and allow traffic from those ranges.
            ip_set = wafv2.IpSet(
                f"{name}-ip-set",
                name=f"{pulumi.get_project()}-{pulumi.get_stack()}-{name}-ip-set",
                description="An IP Set for trusted IPs",
                scope="CLOUDFRONT",  # Use 'REGIONAL' for regional WAF rules.
                addresses=firewall.allowed_cidr_blocks,
                ip_address_version="IPV4",
            )
            rules.append(
                {
                    "name": "allowSpecificIPs",
                    "priority": priority,
                    "action": {"allow": {}},
                    "visibility_config": {
                        "cloudwatch_metrics_enabled": True,
                        "metric_name": "allowSpecificIPsMetric",
                        "sampled_requests_enabled": True,
                    },
                    "statement": {"ip_set_reference_statement": {"arn": ip_set.arn}},
                }
            )
            priority += 1

        log.debug(f"rules: {rules}")
        # Create the WAF resource using the defined rules.
        self.waf = wafv2.WebAcl(
            f"{name}-web-acl",
            #            name=f"{pulumi.get_project()}-{pulumi.get_stack()}-{name}-web-acl",
            scope="REGIONAL",
            default_action=firewall.default_action,
            visibility_config=firewall.visibility_config,
            rules=rules,
        )

    @property
    def arn(self):
        return self.waf.arn
