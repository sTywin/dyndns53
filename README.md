# DynDNS53

DynDNS53 is an implementation for AWS of the dyndns2 protocol used by many DDNS providers such as Dyn and Google Domains. It runs as a AWS Lambda function, via an API Gateway endpoint, and updates records in Route 53 zones. When setup properly, the only service you need to run locally is your favourite DDNS update client. This implementation was tested with `ddclient`.

## Prerequisites

- An Amazon Web Services (AWS) account.
- A domain name you control, with name servers pointing to Route 53.
- A hosted zone for your domain on Route 53.
- An `A` record for your host's FQDN in the hosted zone.
- Patience with AWS Console

## AWS configuration

### Permissions and roles

The Lambda function will require an execution role, and that role needs permission to both read and modify Route 53 records. The included `iam_policy` file will create a security policy allowing your Lambda function to get/set resource record sets in your hosted zone, as well as to create log groups and streams and to put log events to CloudWatch.

1. Modify the `iam_policy` file, replacing `<MY_ZONE_ID>` with your Route 53 zone ID.
1. Sign into AWS and select "Security Credentials" from the drop-down list under your name.
1. Create a policy for the DynDNS53 Lambda execution role:
   1. Select "Policies" from the left-hand menu.
   1. Click "Create Policy" and select "Create Your Own Policy".
   1. Give the policy a name (I used `dyndns53_policy`) and paste the contents of `iam_policy`. Ensure that you have replaced `<MY_ZONE_ID>` with your Route 53 zone ID.
   1. You can "Validate Policy", if you like.
   1. Click "Create Policy"
1. Create an execution role for the DynDNS53 Lambda function:
   1. Select "Roles" from the left-hand menu.
   1. Click "Create New Role" and give it a name (I used `dyndns53_execution`).
   1. Expand "AWS Service Roles" and select "AWS Lambda".
   1. Locate the policy you created above and select it
   1. Click "Next Step", review, and then click "Create Role".

### Lambda function

The Lambda function parses the client update request and performs the update in Route 53.

1. Modify the `conf` dictionary in `dyndns53.py` with your desired configuration, replacing `<username>`, `<password>`, `<host.example.com.>`, and `<MY_ZONE_ID>`. You can also optionally modify the TTL value used when updating the host's record.
   ```
   conf = {
      '<username>:<password>': {
         'hosts': {
            '<host.example.com.>': { # FQDN (don't forget trailing `.`)
               'aws_region': 'us-west-2', # not actually important
               'zone_id': '<MY_ZONE_ID>', # same zone ID as in `iam_polcy`
               'record': {
                  'ttl': 60, # TTL in seconds; should be low for DDNS
                  'type': 'A', # only `A` records supported right now
               },
               'last_update': None, # not currently used
            }
         }
      }
   }
   ```
   You can have multiple `<username>:<password>` combinations, and multiple `<host.example.com>` entries per user. The `dyndns2` protocol uses HTTP basic authentication, so I recommend using randomly generated username/password strings. Note that API Gateway will only respond to HTTPS, so this information is never sent over the internet in the clear.
1. Sign into AWS and navigate to the Lambda Console.
1. Click "Create Lambda Function", and "Skip" selecting a blueprint.
1. Give your function a name (I used `dyndns53_lambda`) and set the runtime to Python 3.9.
1. Paste the contents of `dyndns53.py` into the "Lambda function code" box, making sure you have updated your `conf` appropriately.
1. Select the execution role you created above in the "Role" drop-down list; leave "Handler" as `lambda_function.lambda_handler`.
1. Under "Advanced settings", you may wish to increase the timeout from 3 s to 10 s. Calls from Lambda to other AWS services can sometimes be slow.
1. Click "Next", review, then click "Create Function."

#### Test your Lambda funciton (optional)

You can configure a test event to do trial runs of your Lambda function. Modify the included `sample_lambda_event.json` file, replacing `<host.example.com>` with your DDNS host name, `<MY_HOST_IP>` with the IPv4 address you wish to set, `<MY_SOURCE_IP>` with the IPv4 of the client (if you don't specify `myip` in the request, the source IP is used to set the record), and `<MY_BASE64_USER:PASS>` with the Base-64 encoding of `<username>:<password>`.

If it works, you should see the following result:
```
{
  "status": 200,
  "response": "good <MY_HOST_IP>"
}
```

### API Gateway

The JSON event structure above is the way API Gateway interfaces with AWS Lambda. Now you will configure API Gateway to deliver HTTP requests to the Lambda function as events in this format. Likewise, JSON responses like the above will be converted by API Gateway into HTTP responses to the client. This interface is where the bulk of the frustration lies when working with Lambda and API Gateway.

#### Configure the API

1. Sign into AWS and navigate to the API Gateway console.
1. Click "Create API" and select "Import" under "REST API".
1. Paste the included `sample_swagger2_api.json` file, or click "Select Swagger File" to upload it.
1. Replace the two instances of `<ACCOUNT-NUMBER>` with your AWS account number (without dashes). You can find your account number under your name in the upper-right corner.
1. Update the region names (if not `us-east-1`) and Lambda function names (if not `dyndns53_lambda`) on the same lines as `<ACCOUNT-NUMBER>`, as necessary.
1. Click "Import".

#### Deploy the API

Now that we have configured the API, we need to deploy it to get an access URL.

1. Select `/` from the resource list.
1. Select "Deploy API" from the "Actions" drop-down.
1. Select "[New Stage]" from the "Deployment stage" dropdown.
1. Give your stage a name (I used `v1`; note that this will be part of your URL).
1. Click "Deploy".
1. Record the "Invoke URL" listed at the top of the screen; this is the root URL of your API.

Your API should now be deployed and accessible at the invoke URL you recorded above. You can now configure your client.

## EdgeRouter configuration

If you have a [Ubiquiti EdgeRouter](https://www.ubnt.com/edgemax/edgerouter-lite/), you can use the built-in dynamic DNS functionality, which uses `ddclient` to perform the actual updates. Use the following commands in `configure` mode, replacing fields between `<` and `>` with appropriate values for your configuration.

```
edit service dns dynamic
set service dyndns host-name <host.example.com>
set service dyndns login <username>
set service dyndns password <password>
set service dyndns server <endpoint>.execute-api.<region>.amazonaws.com/<stage>
commit
top
```

The version of `ddclient` shipped with EdgeMax 1.8.0 firmware does not include support for the `googledomains` protocol, which is a subset of the `dyndns2` protocol. The DynDNS53 API more closely resembles the `googledomains` protocol than the full `dyndns2` protocol.

## Other options

- https://aws.amazon.com/blogs/compute/building-a-dynamic-dns-for-route-53-using-cloudwatch-events-and-lambda/
- https://medium.com/aws-activate-startup-blog/building-a-serverless-dynamic-dns-system-with-aws-a32256f0a1d8#.715x7yosd
- https://github.com/GrahamDumpleton/dyndns53
- https://github.com/christopherhein/dynamic53
- https://github.com/goura/dynamic53

## License

See the [LICENSE](LICENSE.md) file for license rights and limitations (MIT).
