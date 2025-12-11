import * as cdk from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';
import * as lambdaEventSources from 'aws-cdk-lib/aws-lambda-event-sources';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';

export class InfrastructureStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // 从 context 读取跨账号 S3 凭证（可选）
    const udemoAccessKeyId = this.node.tryGetContext('udemoAccessKeyId');
    const udemoSecretAccessKey = this.node.tryGetContext('udemoSecretAccessKey');
    const udemoBucket = this.node.tryGetContext('udemoBucket') || 'udemo-us-east-1';
    const udemoRegion = this.node.tryGetContext('udemoRegion') || 'us-east-1';

    // DynamoDB Tables
    const requestTable = new dynamodb.Table(this, 'RequestTable', {
      partitionKey: { name: 'request_id', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    requestTable.addGlobalSecondaryIndex({
      indexName: 'name-created_at-index',
      partitionKey: { name: 'name', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'created_at', type: dynamodb.AttributeType.STRING },
    });

    const frameTable = new dynamodb.Table(this, 'FrameTable', {
      partitionKey: { name: 'request_id', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'frame_index', type: dynamodb.AttributeType.NUMBER },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // SQS Queue
    const batchQueue = new sqs.Queue(this, 'BatchQueue', {
      visibilityTimeout: cdk.Duration.minutes(15),
      retentionPeriod: cdk.Duration.days(1),
    });

    // S3 Results Bucket
    const resultsBucket = new s3.Bucket(this, 'ResultsBucket', {
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    });

    // Lambda Layer for shared code
    const sharedLayer = new lambda.LayerVersion(this, 'SharedLayer', {
      code: lambda.Code.fromAsset('../layer'),
      compatibleRuntimes: [lambda.Runtime.PYTHON_3_12],
    });

    // 构建环境变量（只在提供了凭证时才添加）
    const commonEnv: { [key: string]: string } = {
      REQUEST_TABLE: requestTable.tableName,
      FRAME_TABLE: frameTable.tableName,
      BATCH_QUEUE_URL: batchQueue.queueUrl,
      RESULTS_S3_BUCKET: resultsBucket.bucketName,
      // 启用的 policies（排除使用 Claude 的 streamer_behavior_v2）
      ENABLED_POLICIES: 'drinking_detection,person_appearance,stream_quality,streamer_behavior',
      BEDROCK_MODEL_ID: 'us.amazon.nova-lite-v1:0',
      BEDROCK_REGION: 'us-east-1',
    };

    // 如果提供了 UDEMO 凭证，添加到环境变量
    if (udemoAccessKeyId && udemoSecretAccessKey) {
      commonEnv.UDEMO_AWS_ACCESS_KEY_ID = udemoAccessKeyId;
      commonEnv.UDEMO_AWS_SECRET_ACCESS_KEY = udemoSecretAccessKey;
      commonEnv.UDEMO_S3_BUCKET = udemoBucket;
      commonEnv.UDEMO_S3_REGION = udemoRegion;
    }

    // Request Handler
    const requestHandler = new lambda.Function(this, 'RequestHandler', {
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'request_handler.handler',
      code: lambda.Code.fromAsset('../lambda/handlers'),
      layers: [sharedLayer],
      timeout: cdk.Duration.seconds(120),  // 增加到 120 秒，处理大量文件列表和 SQS 消息
      memorySize: 256,  // 增加内存
      environment: commonEnv,
    });

    requestTable.grantWriteData(requestHandler);
    requestHandler.addToRolePolicy(new iam.PolicyStatement({
      actions: ['s3:ListBucket', 's3:GetObject'],
      resources: ['*'],
    }));

    // Message Dispatcher (异步发送 SQS 消息)
    const messageDispatcher = new lambda.Function(this, 'MessageDispatcher', {
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'message_dispatcher.handler',
      code: lambda.Code.fromAsset('../lambda/handlers'),
      layers: [sharedLayer],
      timeout: cdk.Duration.minutes(5),
      memorySize: 512,
      environment: commonEnv,
    });

    batchQueue.grantSendMessages(messageDispatcher);
    messageDispatcher.grantInvoke(requestHandler);
    requestHandler.addEnvironment('MESSAGE_DISPATCHER_NAME', messageDispatcher.functionName);

    // Batch Processor (Frame Processor)
    const batchProcessor = new lambda.Function(this, 'BatchProcessor', {
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'frame_processor.handler',
      code: lambda.Code.fromAsset('../lambda/handlers'),
      layers: [sharedLayer],
      timeout: cdk.Duration.minutes(15),
      memorySize: 1024,
      environment: commonEnv,
    });

    requestTable.grantReadWriteData(batchProcessor);
    frameTable.grantReadWriteData(batchProcessor);
    batchProcessor.addToRolePolicy(new iam.PolicyStatement({
      actions: ['s3:GetObject'],
      resources: ['*'],
    }));
    batchProcessor.addToRolePolicy(new iam.PolicyStatement({
      actions: ['bedrock:InvokeModel'],
      resources: ['*'],
    }));

    batchProcessor.addEventSource(new lambdaEventSources.SqsEventSource(batchQueue, {
      batchSize: 1,
      maxConcurrency: 100,  // 提高并发度到 100
    }));

    // Completion Handler
    const completionHandler = new lambda.Function(this, 'CompletionHandler', {
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'completion_handler.handler',
      code: lambda.Code.fromAsset('../lambda/handlers'),
      layers: [sharedLayer],
      timeout: cdk.Duration.minutes(5),
      environment: commonEnv,
    });

    requestTable.grantReadWriteData(completionHandler);
    frameTable.grantReadData(completionHandler);
    resultsBucket.grantReadWrite(completionHandler);

    batchProcessor.addEnvironment('COMPLETION_HANDLER_NAME', completionHandler.functionName);
    completionHandler.grantInvoke(batchProcessor);

    // Query Handler
    const queryHandler = new lambda.Function(this, 'QueryHandler', {
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'query_handler.handler',
      code: lambda.Code.fromAsset('../lambda/handlers'),
      layers: [sharedLayer],
      timeout: cdk.Duration.seconds(10),
      environment: commonEnv,
    });

    requestTable.grantReadData(queryHandler);
    resultsBucket.grantRead(queryHandler);

    // Health Check
    const healthCheck = new lambda.Function(this, 'HealthCheck', {
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'health_check.handler',
      code: lambda.Code.fromAsset('../lambda/handlers'),
      layers: [sharedLayer],
      timeout: cdk.Duration.minutes(5),
      environment: { ...commonEnv, COMPLETION_HANDLER_NAME: completionHandler.functionName },
    });

    requestTable.grantReadWriteData(healthCheck);
    frameTable.grantReadWriteData(healthCheck);
    completionHandler.grantInvoke(healthCheck);

    new events.Rule(this, 'HealthCheckRule', {
      schedule: events.Schedule.rate(cdk.Duration.minutes(5)),
      targets: [new targets.LambdaFunction(healthCheck)],
    });

    // API Gateway
    const api = new apigateway.RestApi(this, 'ImageAnalyzerApi', {
      restApiName: 'Image Analyzer API',
      deployOptions: { stageName: 'prod' },
    });

    const requests = api.root.addResource('requests');
    requests.addMethod('POST', new apigateway.LambdaIntegration(requestHandler));

    const requestById = requests.addResource('{id_or_name}');
    requestById.addMethod('GET', new apigateway.LambdaIntegration(queryHandler));

    new cdk.CfnOutput(this, 'ApiUrl', { value: api.url });
    new cdk.CfnOutput(this, 'ResultsBucketName', { value: resultsBucket.bucketName });
  }
}
