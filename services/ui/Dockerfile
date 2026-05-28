FROM node:20-alpine
WORKDIR /app
COPY services/ui/package.json /app/package.json
RUN npm install && npm install --save-dev typescript @types/react @types/react-dom @types/node
COPY services/ui /app
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
ARG NEXT_PUBLIC_DEV_TOOLS
ENV NEXT_PUBLIC_DEV_TOOLS=${NEXT_PUBLIC_DEV_TOOLS}
RUN npm run build
EXPOSE 3000
CMD ["npm", "start"]
