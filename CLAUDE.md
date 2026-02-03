# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

这是一个用 Python 实现的简单 HTTP 正向代理，支持：
- HTTP 方法转发（GET/POST/PUT/DELETE/PATCH/OPTIONS/HEAD）
- 通过 CONNECT 方法实现 HTTPS 隧道
- IPv4/IPv6 支持
- 可选的 Basic 认证

整个实现包含在单个文件（`main.py`）中，除了 Python 3.13+ 标准库外没有外部依赖（pyproject.toml 中的 `requests` 包未被代理本身使用）。

## 运行代理

仅本机使用：
```bash
python3 main.py --listen 127.0.0.1 --port 8080
```

对外提供服务（建议开启认证）：
```bash
python3 main.py --listen 0.0.0.0 --port 8080 --auth user:pass
```

IPv6 监听：
```bash
python3 main.py --listen :: --port 8080 --auth user:pass
```

开启详细日志：
```bash
python3 main.py --listen 127.0.0.1 --port 8080 -v
```

## 架构设计

### 单文件设计

整个代理实现在 `main.py` 中（约 479 行）。核心组件：

1. **请求处理器**（`ProxyHandler` 类，main.py:187-413）
   - 继承自 `http.server.BaseHTTPRequestHandler`
   - 处理常规 HTTP 方法和 CONNECT 隧道
   - 每个请求通过 `ThreadingTCPServer` 在独立线程中处理

2. **HTTP 方法转发**（`_handle_http_method`，main.py:276-344）
   - 从绝对格式 URL（如 `http://example.com/path`）或带 Host 头的源格式解析目标
   - 过滤逐跳首部（Connection、Proxy-Connection 等）
   - 使用 `http.client` 将请求转发到上游
   - 处理分块传输和 Content-Length 响应

3. **CONNECT 隧道**（`do_CONNECT`，main.py:363-390）
   - 建立到目标 host:port 的 TCP 连接
   - 返回 200 Connection Established
   - 使用 `select.select()` 进行双向字节转发（main.py:346-361）

4. **认证**（`_require_auth_if_needed`，main.py:194-204）
   - 通过 `Proxy-Authorization` 头进行 Basic 认证
   - 认证失败返回 407

### 关键实现细节

- **头部过滤**：移除 `HOP_BY_HOP_HEADERS` 中定义的逐跳首部（main.py:12-22）以及 `Connection` 头中列出的其他头部
- **IPv6 支持**：检测 IPv6 地址并使用 `AF_INET6` socket family；绑定到 `::` 时设置 `IPV6_V6ONLY=0` 实现双栈
- **请求体处理**：同时支持 `Content-Length` 和 `Transfer-Encoding: chunked`（`_read_chunked`，main.py:52-80）
- **分块响应重新编码**：如果上游发送分块但 `http.client` 将其解码，代理会为客户端重新编码为分块（main.py:320-328）
- **超时控制**：可配置的 socket 超时（默认 60 秒），用于上游连接和中继操作
- **请求体大小限制**：通过限制请求体大小（默认 32MB）防止内存耗尽

## 配置

所有配置通过命令行参数：
- `--listen`：绑定地址（支持中括号格式如 `[::]`）
- `--port`：端口号
- `--auth user:pass`：启用 Basic 认证
- `--timeout`：socket 超时秒数
- `--max-body`：最大请求体大小（字节）
- `-v/--verbose`：启用访问日志

## 开发环境

使用 `uv` 管理依赖（可选）：
```bash
uv sync
```

代理可以直接用系统 Python 3.13+ 运行，无需安装任何依赖。

## 测试

使用 curl 测试：
```bash
# HTTP 请求
curl --proxy http://127.0.0.1:8080 http://example.com

# HTTPS 请求（通过 CONNECT）
curl --proxy http://127.0.0.1:8080 https://example.com

# 带认证
curl --proxy http://user:pass@127.0.0.1:8080 https://example.com

# IPv6 代理地址
curl --proxy http://user:pass@[::1]:8080 https://example.com
```

## 安全注意事项

- 这是简易实现，适合个人使用/开发调试，不建议用于生产环境
- 对外暴露时务必使用 `--auth` 防止成为开放代理
- 代理不解密 HTTPS 流量（CONNECT 创建直接 TCP 隧道）
- 默认不记录请求/响应日志；使用 `-v` 启用访问日志
