# 阶段1：Node 构建
FROM node:22-alpine AS builder
WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .

# 构建时环境变量（Vite 在构建时替换 import.meta.env.VITE_*）
ARG VITE_API_BASE=
ARG VITE_WS_BASE=
ENV VITE_API_BASE=$VITE_API_BASE
ENV VITE_WS_BASE=$VITE_WS_BASE

RUN npm run build

# 阶段2：nginx 运行（仅 ~10MB）
FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
