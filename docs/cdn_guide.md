# Building a Scalable Content Delivery Network (CDN) with Pulumi: Introducing the `cdn` Function

In modern cloud-based applications, delivering content efficiently and securely to users is essential.  Amazon CloudFront, AWS's Content Delivery Network (CDN) service, is a powerful tool for achieving this. However, setting up and managing a CloudFront distribution can be complex, especially when integrating multiple APIs, with static content, and custom domains.

To simplify this process Cloud Foundry provides the `cdn` function, a Pulumi-based abstraction that streamlines the creation and management of CloudFront distributions. This article will walk you through the `cdn` function, its features, and how to use it in your projects.

---

## What is the `cdn` Function?

The `cdn` function is a high-level Cloud Foundry component that automates the setup of a CloudFront distribution that optimizes content delivery of your application content. This distribution also provides the ability to being together application components such as static content, application API's into a cohesive whole application.

By abstracting away the complexities of CloudFront, the `cdn` function allows you to focus on delivering applications to your users.


## Features of the `cdn` Function

### 1. **Static Site and API Integration**
The `cdn` function supports multiple static sites and APIs as origins. You can define these origins in a structured way, and the function will handle the integration.

### 2. **Custom Domains and SSL Certificates**
The function automates the creation of custom domains, SSL certificates, and DNS records using AWS Certificate Manager (ACM) and Route 53.

### 3. **Geo-Restrictions**
You can restrict access to your content based on geographic locations, ensuring compliance with regional regulations.

### 4. **Error Handling**
Custom error responses can be defined to provide a better user experience when errors occur.

---

## How to Use the `cdn` Function

### Step 1: Define Your Static Sites and APIs
Start by defining the static sites and APIs you want to include in your CloudFront distribution. Each site or API should be represented as a dictionary with the required configuration.

#### Example Static Site:
```python
sites = [
    {
        "name": "my-static-site",
        "bucket_name": "my-static-site-bucket",
        "is_target_origin": True,
    }
]

#### Example API:

```python
apis = [
    {
        "name": "my-api",
        "rest_api": my_rest_api,  # Pulumi API Gateway resource
        "is_target_origin": False,
    }
]
```

### Step 2: Call the cdn Function

Use the cdn function to create your CloudFront distribution. Pass the static sites, APIs, and other optional parameters.

#### Example Usage:

```
from pulumi import export
from cloud_foundry.pulumi.cdn import cdn

# Define static sites and APIs
sites = [
    {
        "name": "my-static-site",
        "bucket_name": "my-static-site-bucket",
        "is_target_origin": True,
    }
]

apis = [
    {
        "name": "my-api",
        "rest_api": my_rest_api,  # Pulumi API Gateway resource
        "is_target_origin": False,
    }
]

# Create the CDN
my_cdn = cdn(
    name="my-cdn",
    sites=sites,
    apis=apis,
    hosted_zone_id="Z3P5QSUBK4POTI",  # Replace with your Route 53 hosted zone ID
    site_domain_name="example.com",
    create_apex=True,
    root_uri="index.html",
)

# Export the CDN domain name
export("cdn_domain_name", my_cdn.domain_name)
```

### Step 3: Deploy with Pulumi

Run the following commands to deploy your CDN using Pulumi:

* Preview the Changes:

* Deploy the Changes:

* Verify the Outputs: After deployment, Pulumi will output the domain name of your CloudFront distribution. Use this domain to access your content.

## Advanced Features

1. Geo-Restrictions

Restrict access to specific countries by providing a list of country codes:

2. Custom Error Responses
Customize error handling for your distribution:

## How It Works
The cdn function internally:

1. Configures Origins: Sets up origins for static sites and APIs.
2. Creates a CloudFront Distribution: Configures cache behaviors, geo-restrictions, and error responses.
3. Sets Up Custom Domains: Automates SSL certificate creation and DNS record setup.
4. Handles Dependencies: Ensures resources are created in the correct order using Pulumi's dependency management.
## Conclusion
The cdn function simplifies the process of creating and managing a CloudFront distribution. Whether you're delivering static content, APIs, or both, this function provides a powerful abstraction to streamline your workflow. By leveraging Pulumi's infrastructure-as-code capabilities, you can deploy scalable and secure CDNs with minimal effort.

Start using the cdn function today to enhance your content delivery strategy!
