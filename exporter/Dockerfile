FROM python:3.12-slim
WORKDIR /app
COPY queue_exporter.py sources.py loadgen.py ./
EXPOSE 9101
USER nobody
ENTRYPOINT ["python", "-u"]
CMD ["queue_exporter.py"]
