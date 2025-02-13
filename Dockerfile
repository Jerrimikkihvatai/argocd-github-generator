FROM python:3.11-slim
WORKDIR /plugin
COPY main.py requirements.txt .
RUN pip3 install -r requirements.txt
ENTRYPOINT python3 /plugin/main.py
