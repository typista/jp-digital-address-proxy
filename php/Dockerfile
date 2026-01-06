FROM php:8.2-cli

RUN apt-get update \
    && apt-get install -y --no-install-recommends libcurl4-openssl-dev pkg-config \
    && docker-php-ext-install curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY shared ./shared
COPY php ./php

RUN chmod +x /app/php/docker-entrypoint.sh

EXPOSE 8000

CMD ["/app/php/docker-entrypoint.sh"]
