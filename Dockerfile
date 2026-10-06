FROM python:3.14-slim
WORKDIR /app
COPY bridge.py /app/bridge.py
RUN useradd --system --uid 10001 --create-home bridge && mkdir -p /data && chown bridge:bridge /data
USER bridge
EXPOSE 8080
ENV DB_PATH=/data/bridge.db
CMD ["python", "/app/bridge.py"]
