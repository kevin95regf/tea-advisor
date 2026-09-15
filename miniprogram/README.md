# 本地 Demo 小程序

两个页面：**输入页 → 结果页**。不发布，只在微信开发者工具里跑，用来验证真机手感与性能。

## 一次性准备

### 1. 安装微信开发者工具

下载：<https://developers.weixin.qq.com/miniprogram/dev/devtools/download.html>
选 **Windows 64 稳定版（Stable Build）**，一路默认安装即可。

装完用微信扫码登录。**不需要注册小程序 AppID** —— 本项目 `project.config.json`
里用的是官方测试号 `"appid": "touristappid"`，游客模式可以直接开发和预览。

> 什么时候才需要真 AppID：要调用 `wx.login`、要用云开发、要真机预览时。
> 到那一步再去 <https://mp.weixin.qq.com> 注册（个人主体免费，1–3 天）。

### 2. 启动后端（每次开发都要）

```powershell
cd D:\work\tea-advisor\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

必须用 `--host 0.0.0.0`（而不是默认的 `127.0.0.1`），否则手机和真机模式连不上。

### 3. 核对局域网 IP

```powershell
Get-NetIPAddress -AddressFamily IPv4 |
  Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' }
```

把结果里的 IPv4 地址填进 `miniprogram/config/env.js` 的 `API_BASE_URL`。

> ⚠️ 这个 IP 会变（换 WiFi、路由器重新分配 IP 都会变）。
> 小程序报 `request:fail` 时，第一件事就是回来核对它。

## 打开项目

1. 开发者工具 → **导入项目**
2. 目录选 `D:\work\tea-advisor\miniprogram`
3. AppID 选「**测试号**」（若已填入 touristappid 会自动识别）
4. 导入后确认：**详情 → 本地设置 → 勾选「不校验合法域名、web-view（业务域名）、TLS 版本以及 HTTPS 证书」**

第 4 步是必须的：本地后端跑在 `http://`（非 HTTPS）上，不勾这一项所有请求都会被拦。

## 预期表现

| 操作 | 预期 |
|---|---|
| 打开输入页 | 顶部无红色告警；有告警说明连不上后端，按页面提示排查 |
| 点示例句子 → 给我建议 | 跳转结果页，显示加载动画，12–18 秒出结果 |
| 结果页 | 「我理解到的」标签 + 1–3 条推荐（饮片/用量/理由/冲泡步骤/注意）+ 判断依据 + 免责声明 |
| 输入「我怀孕了，今天吃了火锅」 | **秒回**，无推荐，提示咨询医师（护栏分支，不调用模型） |
| 第二次提交同样的内容 | 直接秒回，结果页底部标注「来自本地缓存」 |

## 目录说明

```
miniprogram/
├─ app.js / app.json / app.wxss   全局逻辑、页面注册、全局样式
├─ project.config.json            项目配置（含 urlCheck: false）
├─ config/env.js                  ★ 后端地址与超时，换网络只改这里
├─ utils/
│  ├─ request.js                  请求封装：超时、错误翻译、本地缓存
│  └─ format.js                   英文枚举 → 中文标签，体质选项表
└─ pages/
   ├─ index/                      输入页：口述输入 + 示例 + 体质选择 + 后端自检
   └─ result/                     结果页：加载态 / 错误重试 / 解析回显 / 推荐 / 免责声明
```

## 已知限制（本地 demo 阶段的取舍）

- **没有用户体系**：体质存在本机 Storage，没有 `wx.login`，没有服务端用户。
  发布前必须补，否则客户端可以伪造体质。
- **链路质量未验证**：本目录只做过静态检查（JSON/JS/WXML 合法性、格式化逻辑、
  错误翻译），**没有在开发者工具里真实运行过**。首次导入若有渲染问题，属预期范围。
- **12–18 秒等待**：中间有加载动画但没有进度反馈。上线前建议改异步任务 + 轮询，
  并把解析结果先返回（两级返回），让用户先看到「我理解到的」。
- **审核相关缺口**：内容安全检测（`msgSecCheck`）、隐私政策声明、免责声明的
  显著位置，都还没做，属发布前必补项。
