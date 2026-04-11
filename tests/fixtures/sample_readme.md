# Post-mortems

A list of postmortems. See also: ...

## Google

[Google](https://status.cloud.google.com/incident/compute/15056) Compute Engine incidents in us-central1 caused by a software bug in the load balancer. 2015.
[Google](https://status.cloud.google.com/incident/cloud-networking/19009) Cloud networking incident affecting multiple regions due to misconfigured BGP routing. The incident lasted 3 hours and caused degraded performance. January 2019.

## Amazon

[AWS](https://aws.amazon.com/message/5467D2/) EC2 and EBS outage in us-east-1 caused by a network issue in the availability zone. Complete unavailability of multiple services. Recovery took approximately 4 hours. April 2011.
[AWS S3](https://aws.amazon.com/message/41926/) S3 service disruption in us-east-1. The root cause was due to an invalid input in the billing system request processing code. HTTP 503 errors returned for all requests. February 2017.
[Amazon](https://aws.amazon.com/message/680587/) DynamoDB major outage in us-east-1. Caused by memory pressure on the storage servers. Mitigated by restarting the affected servers and deploying a configuration patch. December 2021.

## GitHub

[GitHub](https://github.blog/2018-10-30-oct-21-post-incident-analysis/) GitHub experienced a major outage due to a network partition between US East and US West coast data centers. The incident lasted 24 hours and 11 minutes. The root cause was triggered by a loss of connectivity. October 2018.
[GitHub](https://github.blog/2012-12-26-github-availability-this-week/) Multiple incidents during a week of degraded performance. Caused by database issues and DNS failures. Resolved by patching the database configuration and restarting affected services.

## Microsoft

[Azure](https://azure.microsoft.com/en-us/blog/update-on-azure-storage-service-interruption/) Azure Storage service interruption due to an error in an update to the Azure Storage software stack causing unexpected failures. January 2013.
[Office 365](https://www.microsoft.com/en-us/microsoft-365/blog/2019/02/06/) Exchange Online outage affecting email delivery for 6 hours. Triggered by a configuration change that caused cascading failures in the authentication service.

## Cloudflare

[Cloudflare](https://blog.cloudflare.com/cloudflare-outage/) Global outage affecting all Cloudflare data centers due to a bad software deployment. The outage lasted 27 minutes. The root cause was a regex in the WAF that caused CPU exhaustion across all servers. July 2019.
[Cloudflare](https://blog.cloudflare.com/details-of-the-cloudflare-outage-on-july-17-2020/) Outage caused by a route leak that resulted in traffic being misrouted. Lasted approximately 27 minutes. Resolved by rolling back the routing configuration.

## Stripe

[Stripe](https://support.stripe.com/questions/outage-on-april-10-2011) API downtime affecting payment processing for 2 hours. Caused by a database failure in the primary cluster. Resolved by patching the primary database server.

## Slack

[Slack](https://slack.engineering/slacks-outage-on-january-4th-2021/) Slack outage on January 4, 2021. The root cause was due to a configuration change deployed during a period of high load. The outage lasted approximately 5 hours. Mitigated by deploying a hotfix and restarting the affected services.

## Multiple URLs

[Company X](https://example.com/postmortem) Major outage ([additional analysis](https://example.com/analysis) and [runbook](https://example.com/runbook)) affecting the API gateway. Caused by a memory leak in the connection pool. Duration: 90 minutes. Fixed by restarting the gateway service.

## Facebook

[Facebook](https://engineering.fb.com/2021/10/05/networking-traffic/outage-details/) Six-hour outage affecting all Facebook products due to a BGP routing issue. The root cause was triggered by a configuration change that removed Facebook's BGP routes from the global routing table. Error rate reached 100%. October 4, 2021.

## Multi-line entry

[ExampleCorp](https://example.com/long-incident) A very long incident description that spans
multiple lines in the source file, providing additional context about the root cause
and remediation steps taken to resolve the outage.
