function_name = dyndns53_lambda
role_name = dyndns53_execution
policy_name = dyndns53_policy
gateway_name = DynDNS53
lambda_region = us-east-1

all: upload deploy

upload: build/upload.done

build/upload.done: build/function-arn build/function.zip
	@aws lambda update-function-code \
		--function-name "$(shell cat build/function-arn)" \
		--publish \
		--zip-file fileb://build/function.zip \
		> $@ || rm $@
	@cat $@

build/role-arn:
	@(aws iam get-role \
		--role-name $(role_name) \
		--output text --query Role.Arn \
		> $@ || \
		(rm $@; ${MAKE} create-role build/role-arn))

create-role:
	aws iam create-role \
		--role-name $(role_name) \
		--assume-role-policy-document file://dyndns53_execution.json && \
	aws iam put-role-policy \
		--role-name $(role_name) \
		--policy-name $(policy_name) \
		--policy-document file://iam_policy

build/function-arn:
	@(aws lambda get-function \
		--function-name $(function_name) \
		--output text --query Configuration.FunctionArn \
		> $@ || \
		(rm $@; ${MAKE} create-function build/function-arn))

create-function: build/role-arn build/function.zip
	aws lambda create-function \
		--function-name $(function_name) \
		--runtime python2.7 \
		--role $(shell cat build/role-arn) \
		--handler lambda_function.lambda_handler \
		--timeout 10 \
		--zip-file fileb://build/function.zip

build/lambda_function.py: dyndns53.py
	@cp dyndns53.py build/lambda_function.py

build/function.zip: build/lambda_function.py
	@(cd build/ && zip function.zip lambda_function.py)

build/rest-api-id:
	@aws apigateway get-rest-apis \
		--query 'items[?name==`$(gateway_name)`].id' \
		--output text \
		> $@
	@if [ ! -s $@ ]; then rm $@; ${MAKE} create-rest-api; fi

create-rest-api:
	aws apigateway create-rest-api --name $(gateway_name) \
		--output text \
		--query id \
		> build/rest-api-id || rm build/rest-api-id

build/rest-api-root-id: build/rest-api-id
	@aws apigateway get-resources \
		--rest-api-id $(shell cat build/rest-api-id) \
		--query 'items[?path==`/`].id' \
		--output text \
		> $@

build/nic-resource-id:
	@aws apigateway get-resources \
		--rest-api-id $(shell cat build/rest-api-id) \
		--query 'items[?path==`/nic`].id' \
		--output text \
		> $@
	@if [ ! -s $@ ]; then rm $@; ${MAKE} create-nic-resource; fi

create-nic-resource: build/rest-api-id build/rest-api-root-id
	aws apigateway create-resource \
		--rest-api-id $(shell cat build/rest-api-id) \
		--parent-id $(shell cat build/rest-api-root-id) \
		--path-part "nic" \
		--query id --output text \
		> build/nic-resource-id || rm build/nic-resource-id

build/update-resource-id:
	@aws apigateway get-resources \
		--rest-api-id $(shell cat build/rest-api-id) \
		--query 'items[?path==`/nic/update`].id' \
		--output text \
		> $@
	@if [ ! -s $@ ]; then rm $@; ${MAKE} create-update-resource; fi

create-update-resource: build/rest-api-id build/nic-resource-id
	aws apigateway create-resource \
		--rest-api-id $(shell cat build/rest-api-id) \
		--parent-id $(shell cat build/nic-resource-id) \
		--path-part "update" \
		--query id --output text \
		> build/update-resource-id || rm build/update-resource-id

build/api_mapping_template.json: api_mapping_template
	/bin/echo -n '{"application/json": "' > $@.tmp
	sed -e 's/"/\\"/g' api_mapping_template | awk 1 ORS='\\n' >> $@.tmp
	/bin/echo '"}' >> $@.tmp
	mv $@.tmp $@

build/update-method.done: build/rest-api-id build/update-resource-id
	@(aws apigateway get-method \
		--rest-api-id $(shell cat build/rest-api-id) \
		--resource-id $(shell cat build/update-resource-id) \
		--http-method GET > /dev/null \
		&& touch $@ || ${MAKE} create-update-method)

create-update-method: build/rest-api-id build/update-resource-id build/function-arn build/api_mapping_template.json
	aws apigateway put-method \
		--rest-api-id $(shell cat build/rest-api-id) \
		--resource-id $(shell cat build/update-resource-id) \
		--http-method GET \
		--authorization-type NONE \
		--request-parameters '{"method.request.querystring.myip": false, "method.request.querystring.offline": false, "method.request.querystring.hostname": false, "method.request.header.Authorization": false}'
	aws apigateway put-integration \
		--rest-api-id $(shell cat build/rest-api-id) \
		--resource-id $(shell cat build/update-resource-id) \
		--http-method GET \
		--type AWS \
		--integration-http-method POST \
		--uri 'arn:aws:apigateway:$(lambda_region):lambda:path/2015-03-31/functions/$(shell cat build/function-arn)/invocations' \
		--request-templates file://build/api_mapping_template.json
	for code in 200 500 400 401 403 404; do \
		aws apigateway put-method-response \
			--rest-api-id $(shell cat build/rest-api-id) \
			--resource-id $(shell cat build/update-resource-id) \
			--http-method GET \
			--status-code $$code \
			--response-models '{"text/plain": "Empty"}'; \
	done
	aws apigateway put-integration-response \
		--rest-api-id $(shell cat build/rest-api-id) \
		--resource-id $(shell cat build/update-resource-id) \
		--http-method GET \
		--status-code 200 \
		--response-templates '{"application/json": "$$input.path(\"$$.response\")"}'
	for code in 500 400 401 403 404; do \
		aws apigateway put-integration-response \
			--rest-api-id $(shell cat build/rest-api-id) \
			--resource-id $(shell cat build/update-resource-id) \
			--http-method GET \
			--status-code $$code \
			--selection-pattern ".*\"status\"\\s*:\\s*$$code.*" \
			--response-templates '{"application/json": "$$util.parseJson($$input.path(\"$$.errorMessage\")).response"}'; \
	done
	touch build/update-method.done

deploy: build/deploy.done

build/deploy.done: build/update-method.done build/rest-api-id
	aws apigateway create-deployment \
		--rest-api-id $(shell cat build/rest-api-id) \
		--stage-name v1 \
		> $@ || rm $@
	@cat $@

.PHONY: all upload deploy create-role create-function create-rest-api create-nic-resource create-update-resource
