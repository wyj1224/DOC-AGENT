FROM node:20-alpine AS build
WORKDIR /web
# Override on servers that cannot reach npmjs quickly, e.g. https://registry.npmmirror.com
ARG NPM_REGISTRY=https://registry.npmjs.org
COPY package.json package-lock.json ./
RUN npm ci --registry "$NPM_REGISTRY"
COPY . .
# The API is served from the same origin under /api (see nginx.conf).
RUN VITE_API_BASE=/api npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
