FROM python:3.12-alpine

WORKDIR /app

# git is only needed at install time (one requirement is a git+https dependency),
# so install it as a virtual package and drop it afterwards to keep the image slim.
COPY requirements.txt .
RUN apk add --no-cache --virtual .build-deps git \
    && pip install --no-cache-dir -r requirements.txt \
    && apk del .build-deps

COPY src ./src
COPY templates ./templates

ENTRYPOINT ["python", "src/main.py"]
