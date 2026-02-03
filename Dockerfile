FROM python:3.13-slim

# 创建非 root 用户
RUN useradd -m -u 1000 proxyuser

WORKDIR /app

# 复制代理程序
COPY main.py .

# 切换到非 root 用户
USER proxyuser

# 默认监听所有地址，端口 8080
EXPOSE 8080