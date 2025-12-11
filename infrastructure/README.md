# Image Analyzer Infrastructure

CDK 基础设施代码，用于部署图片分析系统。

## 配置跨账号 S3 访问（可选）

如果需要访问其他 AWS 账号的 S3 bucket，需要配置凭证：

1. 复制示例配置文件：
   ```bash
   cp cdk.context.json.example cdk.context.json
   ```

2. 编辑 `cdk.context.json`，填入实际的 Access Key 和 Secret Key：
   ```json
   {
     "udemoAccessKeyId": "YOUR_ACCESS_KEY_ID",
     "udemoSecretAccessKey": "YOUR_SECRET_ACCESS_KEY",
     "udemoBucket": "udemo-us-east-1",
     "udemoRegion": "us-east-1"
   }
   ```

3. **重要**：`cdk.context.json` 已加入 `.gitignore`，不会被提交到 Git

## 部署

```bash
npm install
npx cdk deploy --require-approval never
```

## 常用命令

* `npm run build`   - 编译 TypeScript
* `npm run watch`   - 监听文件变化并编译
* `npm run test`    - 运行单元测试
* `npx cdk deploy`  - 部署到 AWS
* `npx cdk diff`    - 查看变更
* `npx cdk synth`   - 生成 CloudFormation 模板
