# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

这是一个用 Python 实现的简单 HTTP 正向代理，支持：
- HTTP 方法转发（GET/POST/PUT/DELETE/PATCH/OPTIONS/HEAD）
- 通过 CONNECT 方法实现 HTTPS 隧道
- IPv4/IPv6 支持
- 可选的 Basic 认证
- **自动重新绑定（实验性）**：检测网络地址变化并自动重启

整个实现包含在单个文件（`main.py`）中，除了 Python 3.13+ 标准库外没有外部依赖。

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

启用地址自动重新绑定（实验性）：
```bash
python3 main.py --listen 127.0.0.1 --port 8080 --monitor-interval 10 --monitor-timeout 2
```

当监听地址不可用时（如 WiFi 断开重连、VPN 切换），代理会自动尝试重新绑定到原地址或检测可用的新地址。

## 架构设计

### 单文件设计

整个代理实现在 `main.py` 中（约 650 行）。核心组件：

1. **请求处理器**（`ProxyHandler` 类，main.py:240-467）
   - 继承自 `http.server.BaseHTTPRequestHandler`
   - 处理常规 HTTP 方法和 CONNECT 隧道
   - 每个请求通过 `ThreadingTCPServer` 在独立线程中处理

2. **HTTP 方法转发**（`_handle_http_method`，main.py:330-398）
   - 从绝对格式 URL（如 `http://example.com/path`）或带 Host 头的源格式解析目标
   - 过滤逐跳首部（Connection、Proxy-Connection 等）
   - 使用 `http.client` 将请求转发到上游
   - 处理分块传输和 Content-Length 响应

3. **CONNECT 隧道**（`do_CONNECT`，main.py:417-444）
   - 建立到目标 host:port 的 TCP 连接
   - 返回 200 Connection Established
   - 使用 `select.select()` 进行双向字节转发（`_relay`，main.py:400-415）

4. **认证**（`_require_auth_if_needed`，main.py:248-260）
   - 通过 `Proxy-Authorization` 头进行 Basic 认证
   - 认证失败返回 407

5. **ProxyServer 类**（main.py:470-539）**[新增]**
   - 服务器包装器，支持动态重启
   - 使用 `threading.Lock` 保证线程安全
   - 支持 IPv4/IPv6 地址族自动检测

6. **AddressMonitor 类**（main.py:542-619）**[新增]**
   - 后台监控线程，定期检查地址可用性
   - 当前地址不可用时自动重新绑定
   - 防止快速重新绑定循环（30 秒最小间隔）

7. **地址检测函数**（main.py:170-212）**[新增]**
   - `check_address_available()`：检查地址是否可绑定
   - `auto_detect_address()`：自动检测可用本地地址

### 关键实现细节

- **头部过滤**：移除 `HOP_BY_HOP_HEADERS` 中定义的逐跳首部（main.py:16-27）以及 `Connection` 头中列出的其他头部
- **IPv6 支持**：检测 IPv6 地址并使用 `AF_INET6` socket family；绑定到 `::` 时设置 `IP`V6_V6ONLY=0` 实现双栈
- **请求体处理**：同时支持 `Content-Length` 和 `Transfer-Encoding: chunked`（`_read_chunked`，main.py:57-85）
- **分块响应重新编码**：如果上游发送分块但 `http.client` 将其解码，代理会为客户端重新编码为分块（main.py:359-374）
- **超时控制**：可配置的 socket 超时（默认 60 秒），用于上游连接和中继操作
- **请求体大小限制**：通过限制请求体大小（默认 32MB）防止内存耗尽
- **线程安全**：使用 `threading.Lock` 保护服务器重启操作（ProxyServer 类）
- **自动重新绑定**：后台监控线程定期检查地址可用性，失败时尝试重新绑定到新地址

## 配置

所有配置通过命令行参数：
- `--listen`：绑定地址（支持中括号格式如 `[::]`）
- `--port`：端口号
- `--auth user:pass`：启用 Basic 认证
- `--timeout`：socket 超时秒数
- `--max-body`：最大请求体大小（字节）
- `-v/--verbose`：启用访问日志
- `--monitor-interval`：地址检测间隔（秒），默认 10 秒
- `--monitor-timeout`：地址检测超时（秒），默认 2 秒

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

使用 pytest 运行单元测试：
```bash
# 运行所有测试
python3 -m pytest tests/ -v

# 运行特定测试文件
python3 -m pytest tests/test_address_check.py -v

# 运行带覆盖率报告
python3 -m pytest --cov=.. --cov-report=term-missing
```

## 安全注意事项

- 这是简易实现，适合个人使用/开发调试，不建议用于生产环境
- 对外暴露时务必使用 `--auth` 防止成为开放代理
- 代理不解密 HTTPS 流量（CONNECT 创建直接 TCP 隧道）
- 默认不记录请求/响应日志；使用 `-v` 启用访问日志
