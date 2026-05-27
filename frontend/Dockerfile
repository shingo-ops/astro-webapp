# Stage 1: Build
FROM node:20-slim AS builder

WORKDIR /app

# Vite がビルド時に埋め込む VITE_ 環境変数を受け取る
ARG VITE_FIREBASE_API_KEY
ARG VITE_FIREBASE_AUTH_DOMAIN
ARG VITE_GCP_PROJECT_ID
ENV VITE_FIREBASE_API_KEY=$VITE_FIREBASE_API_KEY
ENV VITE_FIREBASE_AUTH_DOMAIN=$VITE_FIREBASE_AUTH_DOMAIN
ENV VITE_GCP_PROJECT_ID=$VITE_GCP_PROJECT_ID

# 依存関係をコピーしてインストール
COPY package*.json ./
RUN npm install

# ソースコードをコピーしてビルド
COPY . .
RUN npm run build

# Stage 2: Production
FROM nginx:alpine

# ビルド成果物をNginxの公開ディレクトリにコピー
COPY --from=builder /app/dist /usr/share/nginx/html

# カスタムNginx設定（キャッシュヘッダー付き・非rootユーザー用ポート8080）
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 非rootユーザーの作成とファイル権限設定
RUN addgroup -S appgroup && adduser -S appuser -G appgroup \
    && chown -R appuser:appgroup /usr/share/nginx/html \
    && chown -R appuser:appgroup /var/cache/nginx \
    && chown -R appuser:appgroup /var/log/nginx \
    && touch /var/run/nginx.pid \
    && chown appuser:appgroup /var/run/nginx.pid

USER appuser

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
