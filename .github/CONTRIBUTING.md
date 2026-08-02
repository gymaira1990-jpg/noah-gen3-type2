# 贡献指南 (Contributing)

感谢你愿意为 noah-gen3-type2 贡献！本仓库是诺亚三代二型（通用型 AI 认知架构）的公开仓库。

## 贡献方式

- **报告问题**：用 GitHub Issue 模板提交 bug 或功能建议
- **提交代码/方案**：遵循目录编号规范，更新 README + CHANGELOG
- **分享文档**：架构设计、方案总结放到对应子项目目录

## 开发流程

1. Fork 本仓库
2. 创建特性分支：`git checkout -b feat/xxx`
3. 提交变更（遵循提交规范：`类型: 描述`）
4. 推送分支并创建 Pull Request（用 PR 模板）

## 质量标准

- **隐私红线**：绝不提交真实服务器 IP、API 密钥（用 `os.environ.get()` 读取）、SSH 配置、本地路径
- **文档同步**：README 项目清单 / CHANGELOG 必须同步更新
- **格式规范**：代码标注语言，表格保留可读性

## 提交规范

```
feat: 新功能或新方案
fix: 修复问题
docs: 文档变更
refactor: 重构
security: 脱敏/安全修复
chore: 杂项
```

## License

本仓库采用 MIT License，详见 LICENSE 文件。
