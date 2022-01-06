FROM python:3.9.9-slim-buster
WORKDIR /app
COPY requirements.txt covers.py ./
RUN pip install -r requirements.txt
ENTRYPOINT ["python", "covers.py"]
