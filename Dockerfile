FROM python:3.18.0-slim

WORKDIR /app

RUN pip install -r requirements.txt

COPY . . 

CMD ["python", "entrypoint.py"]