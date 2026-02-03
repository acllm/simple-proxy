
# simple-proxy

一个可用的本地/自建 HTTP 正向代理（forward proxy），支持：

- 常见 HTTP 方法转发（`GET/POST/PUT/DELETE/PATCH/OPTIONS/HEAD`）
- `CONNECT` 隧道（用于 HTTPS 代理）
- IPv4 / IPv6 监听
- 可选 Basic 鉴权（强烈建议对外提供服务时开启）

## 运行要求

- Python `>= 3.13`

## 安装依赖

本项目依赖很少，主要用于管理环境（可选）：

- `uv sync`

也可以直接用系统 Python 运行 `main.py`（无需安装额外依赖）。

## 启动代理

仅本机使用（默认）：

```bash
python3 main.py --listen 127.0.0.1 --port 8080
```

给其他机器使用（监听所有地址）：

```bash
python3 main.py --listen 0.0.0.0 --port 8080 --auth user:pass
```

IPv6 监听（例如监听所有 IPv6 地址）：

```bash
python3 main.py --listen :: --port 8080 --auth user:pass
```

启动成功后会打印：

- 实际 bind 的地址（例如 `[::]:8080` 或 `0.0.0.0:8080`）
- 如果 bind 的是通配地址（`::` / `0.0.0.0`），额外打印本机推断的可用访问 IP（便于复制给客户端机器使用）

## 客户端使用示例

### curl

```bash
curl --proxy http://user:pass@<代理机IP>:8080 http://example.com
curl --proxy http://user:pass@<代理机IP>:8080 https://example.com
```

如果代理机使用 IPv6 地址，URL 里需要加中括号：

```bash
curl --proxy http://user:pass@[2001:db8::1234]:8080 https://example.com
```

### 环境变量

```bash
export http_proxy=http://user:pass@<代理机IP>:8080
export https_proxy=http://user:pass@<代理机IP>:8080
```

## 常用参数

- `--listen`：监听地址，如 `127.0.0.1` / `0.0.0.0` / `::1` / `::` / `2001:db8::1`（也支持 `[::]` 这种写法）
- `--port`：监听端口
- `--auth user:pass`：开启 Basic 鉴权（对外提供服务强烈建议开启，避免变成开放代理）
- `--timeout`：socket 超时秒数（默认 60）
- `--max-body`：最大请求体大小（默认 32MiB；用于限制转发大请求）
- `-v/--verbose`：打开访问日志

## 后台启动

### 方式 1：nohup（临时后台运行）

```bash
nohup python3 main.py --listen :: --port 8080 --auth user:pass > proxy.log 2>&1 &
```

- 日志会输出到 `proxy.log`
- 使用 `jobs` 查看后台任务
- 使用 `kill <pid>` 停止进程

### 方式 2：Docker（推荐）

使用 docker-compose：

```bash
docker-compose up -d
```

或直接使用 Docker：

```bash
docker build -t simple-proxy .
docker run -d -p 8080:8080 --name proxy simple-proxy --listen :: --port 8080 --auth user:pass
```

查看日志和管理：

```bash
docker-compose logs -f    # 查看日志
docker-compose stop       # 停止服务
docker-compose restart    # 重启服务
```

### 方式 3：macOS launchd（开机自启）

创建 `~/Library/LaunchAgents/com.proxy.simple.plist`：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.proxy.simple</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/python3</string>
        <string>/Users/YOUR_USERNAME/code-repos/simple-proxy/main.py</string>
        <string>--listen</string>
        <string>::</string>
        <string>--port</string>
        <string>8080</string>
        <string>--auth</string>
        <string>user:pass</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/proxy.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/proxy.err</string>
</dict>
</plist>
```

加载并启动服务：

```bash
launchctl load ~/Library/LaunchAgents/com.proxy.simple.plist
launchctl start com.proxy.simple
```

停止和卸载：

```bash
launchctl stop com.proxy.simple
launchctl unload ~/Library/LaunchAgents/com.proxy.simple.plist
```

### 方式 4：Linux systemd（开机自启）

创建 `/etc/systemd/system/simple-proxy.service`：

```ini
[Unit]
Description=Simple HTTP Proxy
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/path/to/simple-proxy
ExecStart=/usr/bin/python3 main.py --listen :: --port 8080 --auth user:pass
Restart=on-failure
StandardOutput=append:/var/log/simple-proxy.log
StandardError=append:/var/log/simple-proxy.err

[Install]
WantedBy=multi-user.target
```

启用并启动服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable simple-proxy
sudo systemctl start simple-proxy
```

查看状态和日志：

```bash
sudo systemctl status simple-proxy
sudo journalctl -u simple-proxy -f
```

## 工作方式说明

- HTTP：代理会将请求转发到上游站点并把响应返回给客户端。
- HTTPS：代理使用 `CONNECT host:port` 建立 TCP 隧道，仅做字节转发，不解密 TLS 流量。

## 安全注意事项

- 不要在公网直接裸露代理端口；如果必须对外开放，务必开启 `--auth`，并配合防火墙限制来源 IP。
- 这是简易代理实现，适合自用/开发调试，不建议作为高并发/生产级代理服务。
