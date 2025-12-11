# Kiro Rules

## General

- Response in Chiense
- Use --no-pager for any supported command line, eg. AWS CLI, CDK, GIT
- export PYTHONDONTWRITEBYTECODE=1 before run python script, export once is enough.

## Python

- all import should be on top.
- use logging to log, all logs should be written in English in log.log, progress and important log should be print on std.

## Docs

- 文档编写在docs/目录下

- product.md，你要站在资深的产品经理的角度来写。产品经理善于用写文章的方式来表达，文章不同于技术人员的文档，要善于运用段落和文字来阐述清楚需求内容。产品经理是技术人员，对技术了解甚少，像markdown这样的格式产品经理并不擅长。你要把需求内容描写的尽量细致，尤其是各种细节，各种规则等等，写的尽量具体，开发人员阅读后才知道如何设计。另外，文档应该是一篇完整的文章，应该是经过整理和完善的文章，而不是不断追加在末尾的文档，不断追加显得特别不专业。

- tech.md，你要站在资深架构师的角度来写。架构师善于使用Markdown的方式来表达。概念定义、实体图、流程图、时序图、API设计、必要public method定义、响应结构、错误代码、测试方法等等是常见的元素。

- testcase/testcase-*.md，你要站在资深测试人员的角度来写，着重于测试用例的设计，应该语言无关，也不应有架构相关技术内容。

- 文档全部用中文拽写。

## Tech

### Test
- 单元测试断言必须验证具体值而非仅验证存在性。对于可预测的值（固定输入/输出、初始状态、已知格式），使用精确断言（== 5）而非范围断言（>= 1），并验证字段间的逻辑关系和数据格式。对于时间戳等动态值，应验证其在合理范围内（如当前时间前后 60 秒），可创建通用辅助方法进行验证。
- 测试技术文档、测试用例都单独有编写，所以编写测试脚本时候，不需要额外的md说明文件
- 每个测试用例都应该具有"测试目标"，或者是API，或者是某个method，或者其他类似，明确表达test target

