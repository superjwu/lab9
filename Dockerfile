FROM python:3.12-slim

WORKDIR /lab9

COPY . /lab9/

ENV PYTHONUNBUFFERED=1

CMD ["python", "lab9.py", "node"]
