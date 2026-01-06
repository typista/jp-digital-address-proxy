FROM node:20-slim

WORKDIR /app

COPY node/package*.json ./node/
RUN cd node && npm install --production

COPY shared ./shared
COPY node ./node

EXPOSE 8000

CMD ["npm", "start", "--prefix", "/app/node"]
