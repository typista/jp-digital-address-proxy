FROM ruby:3.3-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential git && \
    rm -rf /var/lib/apt/lists/*

COPY ruby/Gemfile ruby/Gemfile.lock /app/
RUN gem install bundler -v 2.5.10 && \
    bundle _2.5.10_ config set --local path '/app/vendor/bundle' && \
    bundle _2.5.10_ install

COPY shared /app/shared
COPY ruby /app/ruby

EXPOSE 8002

WORKDIR /app/ruby

CMD ["bundle", "exec", "ruby", "index.rb"]
