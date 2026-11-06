# 每日直播源 Implementation Plan

**Goal:** 有界刷新、真实帧解码检测、VLC 固定订阅和每日 GitHub Actions。
**Architecture:** 独立 M3U 解析/选择、网络与媒体检测、发布器；运行器组合。
**Tech Stack:** Python 3.12 standard library; ffmpeg/ffprobe; GitHub Actions.
**Spec:** docs/design.md

## Constraints and Review Focus
- 不支持 DRM、登录、付费、网络限制绕过，不保存媒体。
- 每日最多 420 个候选，超时和媒体字节有上限，无付费 runner。
- 来源与授权未知如实注明；GitHub 检测不等于用户网络保证。
- 全部失败不覆盖有效列表，严重跌落也保留并公开告警。
- 测试 Unicode/逗号/恶意标签；HLS 相对路径、主从清单、加密和坏媒体；私网 URL 和重定向；首次空结果与保留策略；实际解码。

## Tasks
- [ ] 写解析/分类/去重/轮转测试，验证失败后实现。
- [ ] 写安全 URL 和 HLS/媒体字节测试，验证失败后实现。
- [ ] 写发布保留策略、报告测试，验证失败后实现。
- [ ] 全部测试和本地生成媒体整合测试。
- [ ] 来源配置、中文 README、定时任务和自动提交。
- [ ] 新建获准公开仓库，上传、首轮运行并验证固定 URL。
