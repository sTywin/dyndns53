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
1. Give your function a name (I used `dyndns53_lambda`) and set the runtime to Python 3.7.
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

This also happens to be the most tedious part of setting up DynDNS53.

#### Configure the API

1. Sign into AWS and navigate to the API Gateway console.
1. Click "Create API" and select "New API".
1. Give your API a name (I used `DynDNS53`) and click "Create API".
1. Create a `dyndns2`-compatible resource:
   1. Select `/` in the resource list.
   1. Drop down "Actions" and select "Create Resource".
   1. Enter `nic` for the resource name, which should auto-populate the path.
   1. Click "Create Resource".
   1. Select `/nic` in the resource list and repeat the above steps, using `update` for the resource name.
   1. You should now have a `/nic/update` resource.
1. Create a `GET` method for the `/nic/update` resource:
   1. Select `/nic/update` in the resource list.
   1. Drop down "Actions" and select "Create Method".
   1. Select "GET" from the drop-down that appears, then click the grey checkmark beside it.
   1. Select "Lambda Function" for the integration type, select the region in which you created the Lambda function, and enter the name you gave your Lambda function above (recall I used `dyndns53_lambda`).
   1. Click "OK" when asked to give API Gateway permission to access your Lambda function.
1. Configure the "GET" method request (note: I'm not sure if configuring the method request is required, but I have it in my setup, so I've included it here):
   1. Select the `GET` method under `/nic/update` in the resource list and click on "Method Request".
   1. Expand "URL Query String Parameters" and add three query strings: `hostname`, `myip`, and `offline`.
   1. Expand "HTTP Request Headers" and add a single header: `Authorization`.
   1. At the top, click "Method Execution" to go back to the previous screen.
1. Configure the integration request to map the request contents into the JSON format our Lambda function expects:
   1. Select the `GET` method under `/nic/update` in the resource list and click on "Integration Request".
   1. Expand "Body Mapping Templates" and add a mapping template for content-type `application/json` (note: you have to explicitly type it in, even though it is already pre-populated in grey).
   1. Paste the contents of the `api_mapping_template` file in the template box and click "Save".
   1. If asked about request body passthrough, use the recommended setting.
   1. At the top, click "Method Execution" to go back to the previous screen.
1. Configure the method responses, which correspond to HTTP response codes:
   1. Select the `GET` method under `/nic/update` in the resource list and click on "Method Response".
   1. Expand the `200` row and change the content type to `text/plain`.
   1. Click "Add Response", enter `500`, and click the grey checkmark to create a method response type for generic server errors.
   1. Expand the `500` row and click "Add Response Model".
   1. Enter `text/plain` and select "Empty" from the drop-down, then click the grey check mark.
   1. Repeat the previous steps for the other response codes that the Lambda function may return: `400`, `401`, `403`, and `404`.
   1. At the top, click "Method Execution" to go back to the previous screen.
1. Configure the integration response to map the JSON response from the Lambda function to HTTP responses sent to the user:
   1. Select the `GET` method under `/nic/update` in the resource list and click on "Integration Response".
   1. Expand the default mapping row, then expand "Body Mapping Templates".
   1. Select `application/json` and populate the template with:
      `$input.path('$.response')`
   1. Click "Save".
   1. Click "Add integration response" and populate the Lambda error regex with:
      `.*"status"\s*:\s*500.*`
   1. Select `500` from the "Method response status" drop-down list.
   1. Expand "Body Mapping Templates" and add a mapping template for `application/json`.
   1. Populate the mapping template with:
      `$util.parseJson($input.path('$.errorMessage')).response`
   1. Click "Save".
   1. Repeat the previous steps for the other repsonse codes that the Lambda function may return: `400`, `401`, `403`, and `404`.
   1. At the top, click "Method Execution" to go back to the previous screen.
1. Optional: create a `POST` method on the `/nic/update` resource and repeat all of the above steps so that it behaves identically to the `GET` method. This is only required for DDNS clients that use the `POST` method with the `dyndns2` protocol.

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
