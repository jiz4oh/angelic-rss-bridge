FROM python:3.14-slim
WORKDIR /app
COPY bridge.py /app/bridge.py
COPY scripts/enrich_history.py /app/scripts/enrich_history.py
RUN mkdir -p /data
EXPOSE 8080
ENV DB_PATH=/data/bridge.db
CMD ["python", "/app/bridge.py"]
