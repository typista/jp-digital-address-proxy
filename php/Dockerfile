FROM php:8.2-cli

RUN apt-get update \
    && apt-get install -y --no-install-recommends libcurl4-openssl-dev pkg-config \
    && docker-php-ext-install curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY shared ./shared
COPY php ./php

EXPOSE 8000

CMD ["php", "-S", "0.0.0.0:8000", "-t", "/app/php", "/app/php/index.php"]
