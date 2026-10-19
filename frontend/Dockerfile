FROM node:22-alpine
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend ./
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
