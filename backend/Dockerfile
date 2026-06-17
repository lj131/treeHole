FROM python:3.11-slim
WORKDIR /app

# 系统依赖（chromadb 纯 Python，edge-tts 无需额外系统包）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 预创建数据目录（运行时卷挂载覆盖）
RUN mkdir -p data memories

EXPOSE 8000

# 禁用 chromadb 遥测 + uvicorn 生产模式
ENV ANONYMIZED_TELEMETRY=false
CMD ["uvicorn", "api.api:app", "--host", "0.0.0.0", "--port", "8000"]
