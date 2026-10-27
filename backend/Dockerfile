# Backend API image (Node.js + Express + Prisma).
FROM node:24-alpine

WORKDIR /app

# Install dependencies first: this layer is cached until package files change.
COPY package.json package-lock.json ./
COPY prisma ./prisma
COPY prisma.config.ts tsconfig.json ./
RUN npm ci && npx prisma generate

COPY src ./src

ENV NODE_ENV=production \
    API_PORT=4000 \
    STORAGE_DIR=/storage
EXPOSE 4000

# Apply any pending database migrations, then start the API.
CMD ["sh", "-c", "npx prisma migrate deploy && npx tsx src/index.ts"]
